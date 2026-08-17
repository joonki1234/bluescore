"""담당: 최지희

응답 재현에 필요한 버전 식별자.

금리 경계와 일부 score 파라미터가 정책 확정 전 값이라는 사실을 버전 이름에도
남긴다. 확정 시 값을 덮어쓰지 않고 새 버전을 만든다.
"""

DEMO_DATA_SNAPSHOT_ID = "dashboard-demo-seed-20260814-v1"
REAL_DATA_SNAPSHOT_ID = "gfw-events-2026-01-01_2026-08-13"
DEMO_MODEL_VERSION = "axis-a-demo-v1__axis-b-demo-v1"
REAL_PARTIAL_MODEL_VERSION = "axis-a-pressure-v1__axis-b-unavailable"
SCORING_RULE_VERSION = "bluescore-0.65a-0.35b-v1"
RATE_TABLE_VERSION = "demo-rate-table-78-68-55-v1"


def response_metadata(source_type: str) -> dict:
    is_real = source_type == "real"
    return {
        "data_snapshot_id": REAL_DATA_SNAPSHOT_ID if is_real else DEMO_DATA_SNAPSHOT_ID,
        "model_version": REAL_PARTIAL_MODEL_VERSION if is_real else DEMO_MODEL_VERSION,
        "scoring_rule_version": SCORING_RULE_VERSION,
        "rate_table_version": RATE_TABLE_VERSION,
        "source_type": source_type,
    }

