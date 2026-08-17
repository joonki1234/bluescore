-- 담당: 최지희
-- 원본 GFW/AIS/TAC 데이터는 이 DB에 넣지 않는다. 파일 참조와 버전만 저장한다.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS score_runs (
    score_run_id TEXT PRIMARY KEY,
    vessel_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_type TEXT NOT NULL,
    data_snapshot_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    scoring_rule_version TEXT NOT NULL,
    rate_table_version TEXT NOT NULL,
    blue_score REAL,
    axis_a_score REAL,
    axis_b_score REAL,
    grade TEXT,
    peer_count INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL,
    report_json TEXT,
    result_hash TEXT,
    report_hash TEXT,
    report_source TEXT,
    report_generated_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_score_runs_vessel_created
    ON score_runs(vessel_id, created_at DESC);

CREATE TABLE IF NOT EXISTS appeals (
    appeal_id TEXT PRIMARY KEY,
    score_run_id TEXT NOT NULL REFERENCES score_runs(score_run_id),
    vessel_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ai_response TEXT NOT NULL DEFAULT '',
    ai_response_source TEXT NOT NULL DEFAULT '',
    response_sent_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('submitted', 'approved', 'held')),
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_appeals_status_submitted
    ON appeals(status, submitted_at DESC);

-- 심사 결정은 이의제기가 아니라 **점수 산출 건**에 매단다.
-- 여신 심사는 이의제기가 없어도 이루어지며, 이의제기는 심사의 입력 중 하나일 뿐이다.
-- appeal_id는 "이 심사가 어떤 이의제기에 대한 답이기도 한가"를 표시하는 선택 항목이다.
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    score_run_id TEXT NOT NULL REFERENCES score_runs(score_run_id),
    appeal_id TEXT UNIQUE REFERENCES appeals(appeal_id),
    decision TEXT NOT NULL CHECK(decision IN ('approve', 'hold')),
    reason TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    final_discount_bp INTEGER,
    decided_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_score_run ON reviews(score_run_id);

CREATE TABLE IF NOT EXISTS chain_commits (
    record_id TEXT PRIMARY KEY,
    score_run_id TEXT NOT NULL REFERENCES score_runs(score_run_id),
    review_id TEXT NOT NULL UNIQUE REFERENCES reviews(review_id),
    result_hash TEXT NOT NULL,
    ledger_mode TEXT NOT NULL CHECK(ledger_mode IN ('local', 'onchain')),
    transaction_hash TEXT,
    block_number INTEGER,
    contract_address TEXT,
    committed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chain_commits_score_run
    ON chain_commits(score_run_id);
