"""담당: 최지희

응답 재현에 필요한 버전 식별자.

금리 경계와 일부 score 파라미터가 정책 확정 전 값이라는 사실을 버전 이름에도
남긴다. 확정 시 값을 덮어쓰지 않고 새 버전을 만든다.
"""

DEMO_DATA_SNAPSHOT_ID = "dashboard-demo-seed-20260814-v1"
# data_new/ 스냅샷 기준(services/real_scoring.py의 DEFAULT_EVENTS_PATH/
# DEFAULT_VESSELS_PATH 참고). 데이터 출처를 바꿀 때는 항상 같이 갱신한다 —
# 안 그러면 응답 재현성 계약이 깨진다.
REAL_DATA_SNAPSHOT_ID = "data_new-gfw-events-2026-04-01_2026-08-14-v2"
DEMO_MODEL_VERSION = "axis-a-demo-v1__axis-b-demo-v1"
# score/axis_a_pressure.py의 raw 결합 방식이 바뀔 때마다 버전을 올려야 한다 —
# 안 올리면 services/workflow.py의 캐시 신선도 체크가 변경을 못 알아채고
# 옛 결과를 계속 돌려준다.
REAL_PARTIAL_MODEL_VERSION = "axis-a-pressure-v2__axis-b-unavailable"
# B축(score/real_axis_b_scoring.py)은 선박별로 실산출 여부가 갈려(톤수 매칭
# 커버리지 43.4%뿐) model_version도 응답마다 달라야 한다. 고정 문자열 하나로는
# 재현성 계약이 안 맞아 axis_b_included를 response_metadata()가 직접 받는다.
REAL_MODEL_VERSION_WITH_B = "axis-a-pressure-v2__axis-b-lightgbm-v1"
SCORING_RULE_VERSION = "bluescore-0.65a-0.35b-v1"
RATE_TABLE_VERSION = "demo-rate-table-78-68-55-v1"


def response_metadata(source_type: str, *, axis_b_included: bool = False) -> dict:
    is_real = source_type == "real"
    if is_real:
        model_version = REAL_MODEL_VERSION_WITH_B if axis_b_included else REAL_PARTIAL_MODEL_VERSION
    else:
        model_version = DEMO_MODEL_VERSION
    return {
        "data_snapshot_id": REAL_DATA_SNAPSHOT_ID if is_real else DEMO_DATA_SNAPSHOT_ID,
        "model_version": model_version,
        "scoring_rule_version": SCORING_RULE_VERSION,
        "rate_table_version": RATE_TABLE_VERSION,
        "source_type": source_type,
    }

