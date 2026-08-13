// GFW Vessels Search 수집 — 국적(flag='KOR') 조건, 전체 목록
// 규칙: rules_common.md (공통), rules_gfw.md (GFW 고유) 참고.
// 이 스크립트는 1단계(수집)만 한다 — 파싱/평탄화/필터링 없음, 원문 그대로 저장.

const fs = require("fs");
const path = require("path");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const RAW_BASE = path.join(PROJECT_ROOT, "raw_data", "gfw", "vessels_search");

// 2026-08-13: 프로젝트 범위가 "한국 국적 전체"에서 "한국 국적 + 어업 선박"으로
// 좁혀짐. datasets 파라미터에는 fishing-vessels 전용 값이 없음(확인됨, 404) —
// 대신 where 절의 combinedSourcesInfo.shiptypes.name 필드로 서버 단 필터링.
// 근거/검증 과정은 rules_gfw.md 7번 표 참고.
const WHERE_CLAUSE = "flag='KOR' AND combinedSourcesInfo.shiptypes.name='FISHING'";
const DATASET = "public-global-vessel-identity:latest";
const LIMIT = 50; // 확정값: rules_gfw.md 7번 표 참고 (51 이상은 422)
const ENDPOINT = "https://gateway.api.globalfishingwatch.org/v3/vessels/search";
const QUERY_KEY = `flag_KOR_shiptype_FISHING__${DATASET}`; // 진행상태를 어떤 조회 조건에 대한 것인지 식별

const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 524]);
const MAX_RETRIES = 3;
const BACKOFF_MS = [2000, 4000, 8000];
const REQUEST_DELAY_MS = 200; // 과도한 연속 호출 방지용 (완화 아님, 페이지네이션 자체는 끝까지 순회)

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

// _progress.json은 IDE 등 다른 프로세스가 열어두면 Windows에서 EBUSY/EPERM으로
// 쓰기가 실패할 수 있다 (파일 잠금은 데이터 문제가 아니라 일시적 충돌이므로
// 재시도 대상으로 취급 — 공통 규칙 3번의 취지를 파일 I/O에도 적용).
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

function findResumableRun() {
  if (!fs.existsSync(RAW_BASE)) return null;
  const dirs = fs
    .readdirSync(RAW_BASE)
    .filter((d) => d.startsWith(`${QUERY_KEY.split("__")[0]}__`) || d.includes("flag_KOR"))
    .sort()
    .reverse();
  for (const d of dirs) {
    const progressPath = path.join(RAW_BASE, d, "_progress.json");
    if (!fs.existsSync(progressPath)) continue;
    const progress = JSON.parse(fs.readFileSync(progressPath, "utf8"));
    if (progress.query_key === QUERY_KEY && progress.status === "in_progress") {
      return { dir: path.join(RAW_BASE, d), progress };
    }
  }
  return null;
}

function buildUrl(sinceToken) {
  const url = new URL(ENDPOINT);
  url.searchParams.set("where", WHERE_CLAUSE);
  url.searchParams.set("datasets[0]", DATASET);
  url.searchParams.set("limit", String(LIMIT));
  if (sinceToken) url.searchParams.set("since", sinceToken);
  return url;
}

async function fetchPage(sinceToken, token) {
  const url = buildUrl(sinceToken);
  let lastErr = null;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const startedAt = Date.now();
    let res;
    try {
      res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch (networkErr) {
      lastErr = networkErr;
      if (attempt < MAX_RETRIES) {
        await sleep(BACKOFF_MS[attempt]);
        continue;
      }
      throw networkErr;
    }
    const responseTimeMs = Date.now() - startedAt;
    const bodyText = await res.text();

    if (res.ok) {
      return { url, status: res.status, bodyText, responseTimeMs, attempt };
    }

    if (RETRYABLE_STATUS.has(res.status) && attempt < MAX_RETRIES) {
      await sleep(BACKOFF_MS[attempt]);
      continue;
    }

    // 재시도 대상이 아니거나(예: 401,422) 재시도 소진 -> 즉시 실패로 반환
    return { url, status: res.status, bodyText, responseTimeMs, attempt, failed: true };
  }
  throw lastErr;
}

async function main() {
  const token = readToken();

  let runDir, pagesDir, metaPath, progress;
  const resumable = findResumableRun();

  if (resumable) {
    runDir = resumable.dir;
    pagesDir = path.join(runDir, "pages");
    metaPath = path.join(runDir, "_meta.jsonl");
    progress = resumable.progress;
    console.log(`[resume] ${runDir} (page ${progress.pages_done + 1}부터 재개, since 커서가 만료됐을 수 있음 — 만료 시 첫 실패에서 명확히 중단됨)`);
  } else {
    const startIso = nowIso();
    const runName = `${QUERY_KEY.split("__")[0]}__${safeTimestampForFilename(startIso)}`;
    runDir = path.join(RAW_BASE, runName);
    pagesDir = path.join(runDir, "pages");
    metaPath = path.join(runDir, "_meta.jsonl");
    fs.mkdirSync(pagesDir, { recursive: true });
    progress = {
      query_key: QUERY_KEY,
      where: WHERE_CLAUSE,
      datasets: [DATASET],
      limit: LIMIT,
      started_at: startIso,
      updated_at: startIso,
      status: "in_progress",
      pages_done: 0,
      entries_collected: 0,
      total_at_first_page: null,
      registry_owners_nonempty_count: 0,
      last_since: null,
      last_error: null,
    };
    await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
    console.log(`[start] new run: ${runDir}`);
  }

  let sinceToken = progress.last_since;
  let pageNum = progress.pages_done;

  while (true) {
    const { url, status, bodyText, responseTimeMs, attempt, failed } = await fetchPage(sinceToken, token);
    const requestedAt = nowIso();

    // 메타(요청 정보)와 본문을 분리 저장 — 토큰은 절대 기록하지 않음
    const paramsForMeta = Object.fromEntries(url.searchParams.entries());
    const metaLine = {
      page: pageNum + 1,
      requested_at: requestedAt,
      url: url.origin + url.pathname,
      params: paramsForMeta,
      status,
      response_time_ms: responseTimeMs,
      retry_attempts: attempt,
    };

    if (failed) {
      metaLine.failed = true;
      fs.appendFileSync(metaPath, JSON.stringify(metaLine) + "\n");
      progress.status = "failed";
      progress.last_error = { page: pageNum + 1, status, body: bodyText, at: requestedAt };
      progress.updated_at = requestedAt;
      await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
      console.error(`[FAILED] page ${pageNum + 1}: HTTP ${status} — ${bodyText}`);
      console.error(`재시도 대상이 아니거나(401/422 등) 3회 재시도 후에도 실패. 커서 기반 페이지네이션이라 다음 페이지를 건너뛸 수 없어 여기서 중단함.`);
      process.exit(1);
    }

    pageNum += 1;
    fs.writeFileSync(path.join(pagesDir, `page_${String(pageNum).padStart(5, "0")}.json`), bodyText);
    fs.appendFileSync(metaPath, JSON.stringify(metaLine) + "\n");

    const body = JSON.parse(bodyText);
    if (progress.total_at_first_page === null) progress.total_at_first_page = body.total;
    progress.entries_collected += body.entries.length;
    progress.registry_owners_nonempty_count += body.entries.filter(
      (e) => Array.isArray(e.registryOwners) && e.registryOwners.length > 0
    ).length;
    progress.pages_done = pageNum;
    progress.last_since = body.since || null;
    progress.updated_at = requestedAt;
    await writeJsonRetry(path.join(runDir, "_progress.json"), progress);

    console.log(
      `[page ${pageNum}] entries=${body.entries.length} cumulative=${progress.entries_collected}/${progress.total_at_first_page} status=${status} ${responseTimeMs}ms`
    );

    if (body.entries.length < LIMIT || progress.entries_collected >= progress.total_at_first_page) {
      progress.status = "complete";
      progress.completed_at = nowIso();
      await writeJsonRetry(path.join(runDir, "_progress.json"), progress);
      console.log(`[complete] pages=${progress.pages_done} entries_collected=${progress.entries_collected} total_at_first_page=${progress.total_at_first_page}`);
      break;
    }

    sinceToken = body.since;
    await sleep(REQUEST_DELAY_MS);
  }
}

main().catch((err) => {
  console.error("[fatal]", err);
  process.exit(1);
});
