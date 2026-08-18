"""담당: 최지희

응답 재현에 필요한 버전 식별자.

금리 경계와 일부 score 파라미터가 정책 확정 전 값이라는 사실을 버전 이름에도
남긴다. 확정 시 값을 덮어쓰지 않고 새 버전을 만든다.
"""

DEMO_DATA_SNAPSHOT_ID = "dashboard-demo-seed-20260814-v1"
# data_new/ 스냅샷 기준 — services/real_scoring.py의
# DEFAULT_EVENTS_PATH/DEFAULT_VESSELS_PATH 참고. 이 상수가 실제 데이터 출처와
# 안 맞으면 응답 재현성 계약이 깨지므로, 데이터 출처를 바꿀 때는 항상 같이
# 갱신해야 한다.
REAL_DATA_SNAPSHOT_ID = "data_new-gfw-events-2026-04-01_2026-08-14-v2"
DEMO_MODEL_VERSION = "axis-a-demo-v1__axis-b-demo-v1"
# axis-a-pressure 버전을 v1→v2로 올림 — score/axis_a_pressure.py의
# compute_axis_a_pressure()가 raw 값을 그대로 가중합하던 걸 population
# z-score 정규화 후 결합하는 방식으로 바꿔서(오동규, 재방문압력 기여비중
# 1%→39%로 개선), 같은 vesselId라도 axis_a_pressure_raw·shap_factors 값이
# 달라진다. 버전을 안 올리면 services/workflow.py의 캐시 신선도 체크가 이
# 변경을 못 알아채고 옛 결과를 계속 돌려준다 — REAL_DATA_SNAPSHOT_ID 갱신
# 때 이미 한 번 겪은 문제와 같은 종류라 김준기·오동규가 각자 알아채고
# 동시에 고쳤다.
REAL_PARTIAL_MODEL_VERSION = "axis-a-pressure-v2__axis-b-unavailable"
# B축 연결(score/real_axis_b_scoring.py) — 선박별로 B축 실산출
# 여부가 갈려서(톤수 매칭 커버리지 43.4%뿐) model_version도 응답마다 달라야
# 한다. 고정 문자열 하나로는 재현성 계약이 안 맞아 axis_b_included를
# response_metadata()가 직접 받게 했다.
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

