"""담당: 최지희

응답 재현에 필요한 버전 식별자.

금리 경계와 일부 score 파라미터가 정책 확정 전 값이라는 사실을 버전 이름에도
남긴다. 확정 시 값을 덮어쓰지 않고 새 버전을 만든다.
"""

import hashlib
import json

DEMO_DATA_SNAPSHOT_ID = "dashboard-demo-seed-20260814-v1"
# data_new/ 스냅샷 기준(services/real_scoring.py의 기본 입력 경로 참고).
# 데이터 출처를 바꿀 때는 항상 같이 갱신한다 —
# 안 그러면 응답 재현성 계약이 깨진다.
# (-v4) 태윤님이 매칭에 TAC 쪽 유일성 강제를 추가(중복배정 787척 제거,
# verified 1,234→713척)하고 이어서 GFW registryInfo 있는 원양선을 후보풀
# 에서 제외(오매칭 1건 확인, 713→712척=13.4% 최종 — CLAUDE.md 참고)했다.
# final_vessel_matches.jsonl 내용이 두 번 더 바뀐 거라 버전을 안 올리면
# 캐시가 중복배정·원양선 오매칭이 섞인 옛 매칭 결과를 계속 돌려준다.
REAL_DATA_SNAPSHOT_ID = "data_new-gfw-events-2026-04-01_2026-08-14-v4"
DEMO_MODEL_VERSION = "axis-a-demo-v1__axis-b-demo-v1"
# score/axis_a_pressure.py의 raw 결합 방식이 바뀔 때마다 버전을 올려야 한다 —
# 안 올리면 services/workflow.py의 캐시 신선도 체크가 변경을 못 알아채고
# 옛 결과를 계속 돌려준다.
REAL_PARTIAL_MODEL_VERSION = "axis-a-pressure-v2__axis-b-unavailable"
# B축(score/real_axis_b_scoring.py)은 선박별로 실산출 여부가 갈려(톤수 매칭
# 커버리지 23.2%뿐) model_version도 응답마다 달라야 한다. 고정 문자열 하나로는
# 재현성 계약이 안 맞아 axis_b_included를 response_metadata()가 직접 받는다.
REAL_MODEL_VERSION_WITH_B = "axis-a-pressure-v2__axis-b-lightgbm-v2"
SCORING_RULE_VERSION = "bluescore-0.65a-0.35b-v1"
RATE_TABLE_VERSION = "demo-rate-table-78-68-55-v1"
REAL_SCORE_PIPELINE_VERSION = "tracked-vessel-and-axis-b-input-v2"


def real_score_version_key(**overrides: str) -> str:
    """현재 실산출 구성요소를 대표하는 짧고 결정론적인 버전 키를 만든다."""
    components = {
        "data_snapshot": REAL_DATA_SNAPSHOT_ID,
        "partial_model": REAL_PARTIAL_MODEL_VERSION,
        "full_model": REAL_MODEL_VERSION_WITH_B,
        "scoring_rule": SCORING_RULE_VERSION,
        "rate_table": RATE_TABLE_VERSION,
        "pipeline": REAL_SCORE_PIPELINE_VERSION,
    }
    unknown = set(overrides) - set(components)
    if unknown:
        raise TypeError(f"알 수 없는 버전 구성요소입니다: {', '.join(sorted(unknown))}")
    components.update(overrides)
    canonical = json.dumps(components, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def real_score_run_id(vessel_id: str, **version_overrides: str) -> str:
    """선박과 현재 실산출 버전에 고유한 scoreRunId를 반환한다."""
    return f"real-score-{vessel_id}-{real_score_version_key(**version_overrides)}"


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

