// GFW Vessels 상세 API 수집 — 3단계(Events)에서 이벤트가 1건이라도 있었던
// vesselId(9,723개)를 우선순위로 대상 삼는다.
// 규칙: rules_common.md (공통), rules_gfw.md (GFW 고유) 참고.
// 2단계(수집)만 한다 — 파싱/평탄화/필터링 없음, 원문 그대로 저장.
//
// 2026-08-13: 원래 목표는 32,105개(검색 결과 31,605 entry의 distinct
// vesselId) 전체였으나, 이벤트 있는 9,723척을 먼저 상세조회하도록 우선
// 순위를 바꿨다. 톤수 등 값 기반 필터링이 아니라 구조적 이유(이벤트가
// 없으면 후속 지표 계산 자체가 불가능함) — 근거는 rules_gfw.md 2-2번.
// 이벤트 0건인 22,382척은 제외가 아니라 보류이며, vesselId는 1단계 raw
// (vessels_search)에 그대로 남아있어 나중에 언제든 상세조회 가능하다.
// 32,105 전체 대상 실행은 vessel_detail__2026-08-13T08-16-00.192Z 폴더에
// 1,357건 부분완료 상태로 보존돼 있다(그 폴더 _progress.json 참고).
//
// 검색(1단계)과 달리 상세조회는 항목끼리 완전히 독립적이므로:
// - 커서 없이 "이미 저장된 파일이 있으면 건너뛴다" 방식으로 재개한다
// - 한 건 실패가 전체를 막지 않는다 (공통 규칙 3번) — 재시도 소진 시
//   실패로 기록하고 다음 vesselId로 계속 진행한다
// - 독립적인 요청이라 동시성(CONCURRENCY)을 둬서 32,105건을 현실적인
//   시간 안에 끝낸다 (검색 페이지네이션은 커서 의존이라 병렬화 불가했지만
//   상세조회는 그런 제약이 없음)

const fs = require("fs");
const path = require("path");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
// 대상 목록 출처: 3단계(Events) 수집 완료 시 저장된, 이벤트 1건 이상 있는
// vesselId 목록 (9,723개). 32,105 전체가 아니라 이 파일을 그대로 읽는다 —
// 재계산하지 않음으로써 "이벤트 있음"의 정의가 events 단계와 항상 일치하게 함.
const EVENTS_RUN_VESSELS_WITH_EVENTS = path.join(
  PROJECT_ROOT,
  "raw_data",
  "gfw",
  "events",
  "events__2026-08-13T08-22-34.917Z",
  "vessels_with_events.json"
);
const DETAIL_RAW_BASE = path.join(PROJECT_ROOT, "raw_data", "gfw", "vessels_detail");

const DATASET = "public-global-vessel-identity:latest";
const ENDPOINT_BASE = "https://gateway.api.globalfishingwatch.org/v3/vessels";
const QUERY_KEY = "vessel_detail_events_priority__source_events__2026-08-13T08-22-34.917Z";

const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 524]);
const MAX_RETRIES = 3;
const BACKOFF_MS = [2000, 4000, 8000];
const CONCURRENCY = 24; // 8에서 상향 (2026-08-13) — 상세조회는 항목간 완전 독립이라 병렬화에
// 제약이 없음(4Wings처럼 동시 리포트 1개 제한 같은 게 문서화돼있지 않음). 429가 뜨면
// 기존 재시도/백오프 로직이 알아서 속도를 늦추므로 안전하게 올릴 수 있음.

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
  const ids = JSON.parse(fs.readFileSync(EVENTS_RUN_VESSELS_WITH_EVENTS, "utf8"));
  return [...ids].sort();
}

function findResumableRun() {
  if (!fs.existsSync(DETAIL_RAW_BASE)) return null;
  const dirs = fs.readdirSync(DETAIL_RAW_BASE).sort().reverse();
  for (const d of dirs) {
    const progressPath = path.join(DETAIL_RAW_BASE, d, "_progress.json");
    if (!fs.existsSync(progressPath)) continue;
    const progress = JSON.parse(fs.readFileSync(progressPath, "utf8"));
    if (progress.query_key === QUERY_KEY && progress.status === "in_progress") {
      return { dir: path.join(DETAIL_RAW_BASE, d), progress };
    }
  }
  return null;
}

async function fetchDetail(vesselId, token) {
  const url = new URL(`${ENDPOINT_BASE}/${encodeURIComponent(vesselId)}`);
  url.searchParams.set("dataset", DATASET);
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
      return { url, status: null, bodyText: String(networkErr), responseTimeMs: Date.now() - startedAt, attempt, failed: true };
    }
    const responseTimeMs = Date.now() - startedAt;
    const bodyText = await res.text();

    if (res.ok) return { url, status: res.status, bodyText, responseTimeMs, attempt };

    if (RETRYABLE_STATUS.has(res.status) && attempt < MAX_RETRIES) {
      await sleep(BACKOFF_MS[attempt]);
      continue;
    }
    return { url, status: res.status, bodyText, responseTimeMs, attempt, failed: true };
  }
  return { url, status: null, bodyText: String(lastErr), responseTimeMs: 0, attempt: MAX_RETRIES, failed: true };
}

async function main() {
  const token = readToken();
  const targetIds = extractTargetVesselIds();
  console.log(`[target] distinct vesselId count: ${targetIds.length}`);

  let runDir, detailsDir, metaPath, progress;
  const resumable = findResumableRun();

  if (resumable) {
    runDir = resumable.dir;
    detailsDir = path.join(runDir, "details");
    metaPath = path.join(runDir, "_meta.jsonl");
    progress = resumable.progress;
    console.log(`[resume] ${runDir} (완료 ${progress.completed_count}/${progress.total_target}, 이미 저장된 파일은 재요청 생략)`);
  } else {
    const startIso = nowIso();
    const runName = `${QUERY_KEY.split("__")[0]}__${safeTimestampForFilename(startIso)}`;
    runDir = path.join(DETAIL_RAW_BASE, runName);
    detailsDir = path.join(runDir, "details");
    metaPath = path.join(runDir, "_meta.jsonl");
    fs.mkdirSync(detailsDir, { recursive: true });
    progress = {
      query_key: QUERY_KEY,
      source_vessel_list: EVENTS_RUN_VESSELS_WITH_EVENTS,
      scope_note: "이벤트 1건 이상 있는 vesselId만 대상 (구조적 우선순위, 값 기반 필터링 아님). 이벤트 0건 22,382척은 보류 — rules_gfw.md 2-2번 참고.",
      dataset: DATASET,
      started_at: startIso,
      updated_at: startIso,
      status: "in_progress",
      total_target: targetIds.length,
      completed_count: 0,
      failed: [], // [{vesselId, status, body, at}]
      registry_matched_count: 0,
      registry_unmatched_count: 0,
      registry_owners_nonempty_count: 0,
    };
    await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
    console.log(`[start] new run: ${runDir}`);
  }

  // 진행 상태 파일은 여러 워커가 동시에 건드리므로 순차 직렬화한다
  let writeQueue = Promise.resolve();
  function withLock(fn) {
    const p = writeQueue.then(fn, fn);
    writeQueue = p.catch(() => {});
    return p;
  }

  let completedThisRun = 0;
  let failedThisRun = 0;
  const total = targetIds.length;
  let nextIndex = 0;

  async function worker() {
    while (true) {
      const i = nextIndex++;
      if (i >= total) return;
      const vesselId = targetIds[i];
      const detailPath = path.join(detailsDir, `${vesselId}.json`);

      if (fs.existsSync(detailPath)) continue; // 이미 완료된 항목은 건너뛴다 (재개)

      const { url, status, bodyText, responseTimeMs, attempt, failed } = await fetchDetail(vesselId, token);
      const requestedAt = nowIso();
      const paramsForMeta = Object.fromEntries(url.searchParams.entries());
      const metaLine = {
        vesselId,
        requested_at: requestedAt,
        url: url.origin + url.pathname,
        params: paramsForMeta,
        status,
        response_time_ms: responseTimeMs,
        retry_attempts: attempt,
      };

      if (failed) {
        metaLine.failed = true;
        await withLock(async () => {
          fs.appendFileSync(metaPath, JSON.stringify(metaLine) + "\n");
          progress.failed.push({ vesselId, status, body: bodyText.slice(0, 500), at: requestedAt });
          progress.updated_at = requestedAt;
          await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
        });
        failedThisRun++;
        console.error(`[FAILED] ${vesselId}: HTTP ${status}`);
        continue; // 이 항목만 실패 처리하고 다음으로 진행 (공통 규칙 3번)
      }

      fs.writeFileSync(detailPath, bodyText);
      const body = JSON.parse(bodyText);
      const registryMatched = Array.isArray(body.registryInfo) && body.registryInfo.length > 0;
      const ownersNonEmpty = Array.isArray(body.registryOwners) && body.registryOwners.length > 0;

      await withLock(async () => {
        fs.appendFileSync(metaPath, JSON.stringify(metaLine) + "\n");
        progress.completed_count += 1;
        if (registryMatched) progress.registry_matched_count += 1;
        else progress.registry_unmatched_count += 1;
        if (ownersNonEmpty) progress.registry_owners_nonempty_count += 1;
        progress.updated_at = requestedAt;
        await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
      });
      completedThisRun++;

      if ((completedThisRun + failedThisRun) % 200 === 0) {
        console.log(
          `[progress] ${progress.completed_count}/${total} done, ${progress.failed.length} failed (this run: +${completedThisRun} ok / +${failedThisRun} failed)`
        );
      }
    }
  }

  await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()));

  progress.status = progress.failed.length > 0 ? "complete_with_failures" : "complete";
  progress.completed_at = nowIso();
  await writeJsonRetry(path.join(runDir, "_progress.json"), progress);

  console.log(
    `[complete] status=${progress.status} completed=${progress.completed_count}/${total} failed=${progress.failed.length} registry_matched=${progress.registry_matched_count} registry_unmatched=${progress.registry_unmatched_count}`
  );
}

main().catch((err) => {
  console.error("[fatal]", err);
  process.exit(1);
});
