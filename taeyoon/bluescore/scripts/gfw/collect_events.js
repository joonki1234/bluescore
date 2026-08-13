// GFW Events API 수집 — 1단계(Search)에서 확보한 vesselId 전체 대상,
// 이벤트 타입 5종(FISHING, GAP, PORT_VISIT, ENCOUNTER, LOITERING) 동시 요청.
// 규칙: rules_common.md (공통), rules_gfw.md (GFW 고유) 참고.
// 3단계(수집)만 한다 — 파싱/평탄화/필터링 없음, 원문 그대로 저장.
//
// vesselId 배치: Events API는 vessels[] 배열을 한 호출에 최대 20개까지
// 받는다(2026-08-13 실제 호출로 확인, 21개부터 422). 상세조회와 마찬가지로
// distinct vesselId(32,105개, entry 31,605건과 다름 — rules_gfw.md 2-1번)를
// 대상으로 한다.
//
// 조회 기간: rules_common.md 5번 반기 규칙 — 오늘이 속한 반기가 아직
// 안 끝났으면 직전 완결 반기 시작일부터 오늘까지. 하드코딩하지 않고
// 실행 시점 기준으로 매번 계산한다.
//
// 배치(20개 단위)가 실패 단위 — 한 배치가 재시도 소진 후에도 실패하면
// 그 배치(최대 20척)만 실패로 기록하고 다음 배치로 계속 진행한다
// (공통 규칙 3번). 배치 안에 어떤 vesselId가 있었는지 실패 기록에 남겨서
// 나중에 그 vesselId들만 추려 재시도할 수 있게 한다.

const fs = require("fs");
const path = require("path");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const SEARCH_RUN_DIR = path.join(
  PROJECT_ROOT,
  "raw_data",
  "gfw",
  "vessels_search",
  "flag_KOR_shiptype_FISHING__2026-08-13T07-49-14.068Z",
  "pages"
);
const EVENTS_RAW_BASE = path.join(PROJECT_ROOT, "raw_data", "gfw", "events");

const EVENT_DATASETS = [
  "public-global-fishing-events:latest",
  "public-global-port-visits-events:latest",
  "public-global-encounters-events:latest",
  "public-global-loitering-events:latest",
  "public-global-gaps-events:latest",
];
const ENDPOINT = "https://gateway.api.globalfishingwatch.org/v3/events";
const BATCH_SIZE = 20; // 확정값: 21개부터 422
const PAGE_LIMIT = 1000; // 확정값: 최소 1000까지는 422 없이 동작 확인됨
const QUERY_KEY = "events__source_flag_KOR_shiptype_FISHING__2026-08-13T07-49-14.068Z";

const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 524]);
const MAX_RETRIES = 3;
const BACKOFF_MS = [2000, 4000, 8000];
const CONCURRENCY = 12;

function readToken() {
  if (process.env.GFW_API_TOKEN) return process.env.GFW_API_TOKEN;
  const envPath = path.join(PROJECT_ROOT, ".env");
  const text = fs.readFileSync(envPath, "utf8");
  const m = text.match(/^GFW_API_TOKEN=(.+)$/m);
  if (!m) throw new Error("GFW_API_TOKEN not found in .env");
  return m[1].trim();
}

function nowIso() {
  return new Date().toISOString();
}
function safeTimestampForFilename(iso) {
  return iso.replace(/:/g, "-");
}
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
function ymd(d) {
  return d.toISOString().slice(0, 10);
}

// 공통 규칙 5번: 고정 반기(H1 1/1~6/30, H2 7/1~12/31), 추출범위 = 직전 완결
// 반기 시작일 ~ 오늘. 하드코딩 금지, 실행 시점 기준 매번 계산.
function computeHalfYearRange(today = new Date()) {
  const y = today.getUTCFullYear();
  const isH1 = today.getUTCMonth() < 6; // 0-5월이면 H1 진행중
  const startYear = isH1 ? y - 1 : y;
  const startMonth = isH1 ? 6 : 0; // 직전 완결 반기: H1 진행중이면 작년 H2(7월), H2 진행중이면 올해 H1(1월)
  const startDate = new Date(Date.UTC(startYear, startMonth, 1));
  return { start: ymd(startDate), end: ymd(today) };
}

async function writeJsonRetry(filePath, obj, retries = 8, delayMs = 250) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      fs.writeFileSync(filePath, JSON.stringify(obj, null, 2));
      return;
    } catch (err) {
      const retryable = err.code === "EBUSY" || err.code === "EPERM" || err.code === "EACCES";
      if (!retryable || attempt === retries) throw err;
      await sleep(delayMs);
    }
  }
}

function extractTargetVesselIds() {
  const files = fs.readdirSync(SEARCH_RUN_DIR).filter((f) => f.endsWith(".json")).sort();
  const ids = new Set();
  for (const f of files) {
    const body = JSON.parse(fs.readFileSync(path.join(SEARCH_RUN_DIR, f), "utf8"));
    for (const e of body.entries) {
      for (const c of e.combinedSourcesInfo || []) {
        if (c.vesselId) ids.add(c.vesselId);
      }
    }
  }
  return [...ids].sort();
}

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function findResumableRun() {
  if (!fs.existsSync(EVENTS_RAW_BASE)) return null;
  const dirs = fs.readdirSync(EVENTS_RAW_BASE).sort().reverse();
  for (const d of dirs) {
    const progressPath = path.join(EVENTS_RAW_BASE, d, "_progress.json");
    if (!fs.existsSync(progressPath)) continue;
    const progress = JSON.parse(fs.readFileSync(progressPath, "utf8"));
    if (progress.query_key === QUERY_KEY && progress.status === "in_progress") {
      return { dir: path.join(EVENTS_RAW_BASE, d), progress };
    }
  }
  return null;
}

function buildUrl(vesselBatch, offset, dateRange) {
  const url = new URL(ENDPOINT);
  vesselBatch.forEach((id, i) => url.searchParams.set(`vessels[${i}]`, id));
  EVENT_DATASETS.forEach((ds, i) => url.searchParams.set(`datasets[${i}]`, ds));
  url.searchParams.set("start-date", dateRange.start);
  url.searchParams.set("end-date", dateRange.end);
  url.searchParams.set("limit", String(PAGE_LIMIT));
  url.searchParams.set("offset", String(offset));
  return url;
}

async function fetchPage(url, token) {
  let lastErr = null;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const startedAt = Date.now();
    let res;
    try {
      res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    } catch (networkErr) {
      lastErr = networkErr;
      if (attempt < MAX_RETRIES) {
        await sleep(BACKOFF_MS[attempt]);
        continue;
      }
      return { status: null, bodyText: String(networkErr), responseTimeMs: Date.now() - startedAt, attempt, failed: true };
    }
    const responseTimeMs = Date.now() - startedAt;
    const bodyText = await res.text();
    if (res.ok) return { status: res.status, bodyText, responseTimeMs, attempt };
    if (RETRYABLE_STATUS.has(res.status) && attempt < MAX_RETRIES) {
      await sleep(BACKOFF_MS[attempt]);
      continue;
    }
    return { status: res.status, bodyText, responseTimeMs, attempt, failed: true };
  }
  return { status: null, bodyText: String(lastErr), responseTimeMs: 0, attempt: MAX_RETRIES, failed: true };
}

async function main() {
  const token = readToken();
  const targetIds = extractTargetVesselIds();
  const dateRange = computeHalfYearRange(new Date());
  const batches = chunk(targetIds, BATCH_SIZE);
  console.log(`[target] distinct vesselId: ${targetIds.length}, batches: ${batches.length}, range: ${dateRange.start}~${dateRange.end}`);

  let runDir, batchesDir, metaPath, progress;
  const resumable = findResumableRun();

  if (resumable) {
    runDir = resumable.dir;
    batchesDir = path.join(runDir, "batches");
    metaPath = path.join(runDir, "_meta.jsonl");
    progress = resumable.progress;
    console.log(`[resume] ${runDir} (완료 ${progress.completed_batches}/${progress.total_batches})`);
  } else {
    const startIso = nowIso();
    const runName = `events__${safeTimestampForFilename(startIso)}`;
    runDir = path.join(EVENTS_RAW_BASE, runName);
    batchesDir = path.join(runDir, "batches");
    metaPath = path.join(runDir, "_meta.jsonl");
    fs.mkdirSync(batchesDir, { recursive: true });
    progress = {
      query_key: QUERY_KEY,
      source_search_run: SEARCH_RUN_DIR,
      datasets: EVENT_DATASETS,
      date_range: dateRange,
      batch_size: BATCH_SIZE,
      started_at: startIso,
      updated_at: startIso,
      status: "in_progress",
      total_target_vessels: targetIds.length,
      total_batches: batches.length,
      completed_batches: 0,
      total_events_collected: 0,
      events_by_type: {},
      vessels_with_events: [], // 채워지면 매우 커질 수 있어 완료 후 별도 파일로 옮김 (아래 참고)
      failed_batches: [], // [{batchIndex, vesselIds, status, body, at}]
    };
    await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
    console.log(`[start] new run: ${runDir}`);
  }

  // vessels_with_events는 set으로 메모리에서만 관리 (progress.json에 매번 통째로 쓰면 너무 커짐)
  const vesselsWithEventsSet = new Set(progress.vessels_with_events || []);
  progress.vessels_with_events = undefined; // progress.json 파일 비대해지는 것 방지, 완료시 별도 저장

  let writeQueue = Promise.resolve();
  function withLock(fn) {
    const p = writeQueue.then(fn, fn);
    writeQueue = p.catch(() => {});
    return p;
  }

  let nextBatchIndex = 0;

  async function worker() {
    while (true) {
      const bIdx = nextBatchIndex++;
      if (bIdx >= batches.length) return;
      const vesselBatch = batches[bIdx];
      const batchFilePrefix = path.join(batchesDir, `batch_${String(bIdx + 1).padStart(5, "0")}`);

      if (fs.existsSync(`${batchFilePrefix}_page001.json`)) continue; // 이미 완료된 배치는 건너뜀 (재개)

      let offset = 0;
      let pageNum = 0;
      let batchTotal = null;
      let batchFailed = null;
      const localEventsByType = {};
      const localVesselIdsWithEvents = new Set();

      while (true) {
        pageNum++;
        const url = buildUrl(vesselBatch, offset, dateRange);
        const { status, bodyText, responseTimeMs, attempt, failed } = await fetchPage(url, token);
        const requestedAt = nowIso();
        const paramsForMeta = Object.fromEntries(url.searchParams.entries());
        const metaLine = {
          batch: bIdx + 1,
          page: pageNum,
          requested_at: requestedAt,
          url: url.origin + url.pathname,
          params: paramsForMeta,
          status,
          response_time_ms: responseTimeMs,
          retry_attempts: attempt,
        };

        if (failed) {
          metaLine.failed = true;
          await withLock(() => fs.appendFileSync(metaPath, JSON.stringify(metaLine) + "\n"));
          batchFailed = { batchIndex: bIdx + 1, vesselIds: vesselBatch, status, body: bodyText.slice(0, 500), at: requestedAt };
          console.error(`[FAILED] batch ${bIdx + 1} page ${pageNum}: HTTP ${status}`);
          break;
        }

        fs.writeFileSync(`${batchFilePrefix}_page${String(pageNum).padStart(3, "0")}.json`, bodyText);
        await withLock(() => fs.appendFileSync(metaPath, JSON.stringify(metaLine) + "\n"));

        const body = JSON.parse(bodyText);
        if (batchTotal === null) batchTotal = body.total;
        for (const ev of body.entries) {
          localEventsByType[ev.type] = (localEventsByType[ev.type] || 0) + 1;
          if (ev.vessel && ev.vessel.id) localVesselIdsWithEvents.add(ev.vessel.id);
        }

        if (body.entries.length < PAGE_LIMIT || body.nextOffset === null || body.nextOffset === undefined) {
          break; // 이 배치의 마지막 페이지
        }
        offset = body.nextOffset;
      }

      await withLock(async () => {
        progress.completed_batches += 1;
        if (batchFailed) {
          progress.failed_batches.push(batchFailed);
        } else {
          for (const [type, count] of Object.entries(localEventsByType)) {
            progress.events_by_type[type] = (progress.events_by_type[type] || 0) + count;
            progress.total_events_collected += count;
          }
          for (const vid of localVesselIdsWithEvents) vesselsWithEventsSet.add(vid);
        }
        progress.updated_at = nowIso();
        await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
      });

      if (progress.completed_batches % 100 === 0) {
        console.log(
          `[progress] ${progress.completed_batches}/${batches.length} batches, events=${progress.total_events_collected}, failed_batches=${progress.failed_batches.length}`
        );
      }
    }
  }

  await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()));

  progress.status = progress.failed_batches.length > 0 ? "complete_with_failures" : "complete";
  progress.completed_at = nowIso();
  progress.vessels_with_events_count = vesselsWithEventsSet.size;
  progress.vessels_without_events_count = targetIds.length - vesselsWithEventsSet.size;
  await writeJsonRetry(path.join(runDir, "vessels_with_events.json"), [...vesselsWithEventsSet].sort());
  await writeJsonRetry(path.join(runDir, "_progress.json"), progress);

  console.log(
    `[complete] status=${progress.status} batches=${progress.completed_batches}/${batches.length} events=${progress.total_events_collected} vessels_with_events=${progress.vessels_with_events_count} vessels_without_events=${progress.vessels_without_events_count} failed_batches=${progress.failed_batches.length}`
  );
  console.log(`[events_by_type]`, progress.events_by_type);
}

main().catch((err) => {
  console.error("[fatal]", err);
  process.exit(1);
});
