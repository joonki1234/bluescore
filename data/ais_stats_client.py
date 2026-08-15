"""
담당: 김준기, 오동규

해양수산부_선박위치정보(연안AIS) 통계정보 서비스 (공공데이터포털, data.go.kr/data/15084033)
클라이언트.

2026-08-14 실제 활용가이드(엑셀)로 스펙 확정 — 이전 버전(추측)의 End Point는
NO_OPENAPI_SERVICE_ERROR로 틀린 것이 실측 확인됨. data.go.kr에 이 서비스가
"API 유형: LINK"로 분류돼 있던 이유: apis.data.go.kr 게이트웨이가 아니라
해사안전관리과가 자체 운영하는 GICOMS 서버(gicoms.go.kr)에 있다
(data/marine_weather_client.py와 동일한 패턴).

data.go.kr 활용신청 상세엔 실제로 3개 오퍼레이션이 있는데 그중 2개(구역별
통계 WMS, 해양구역 GRID WMS)는 응답이 image/png(지도 이미지)라 데이터
파이프라인에 못 쓴다. 이 클라이언트는 JSON을 주는 **"날짜별 선박위치정보
(AIS) 통계정보 WFS"** 하나만 다룬다.

요청 URL: http://www.gicoms.go.kr/kodispub/openApi/wfs.do
파라미터: domain(신청한 도메인, 필수), apikey(발급키, 필수),
    typeName(레이어명, 필수, 예: "lage_ship_stats_view"),
    offeryear(요청 데이터 년도, 선택, 예: 2019)
응답 필드(활용가이드 기준): geom(공간정보), ais(AIS 통계값), ship_dt(통계
    날짜), ship_time(통계 시각), map_gb_cd(맵 구분, 예: "2 대해구도"),
    ctgr_cd(카테고리구분, 예: "13 연안AIS"), map_nm(구역번호)

TODO(김태윤): 위 응답 필드 설명은 활용가이드 표 기준이고, 실제 라이브
응답의 최상위 구조(단순 배열인지 GeoJSON FeatureCollection인지 등)와
geom/각 필드의 정확한 타입은 아직 실제 응답으로 검증 전이다 — 소규모
테스트 호출로 확정할 것(rules_common.md 8번).
"""

import os
from typing import List, Optional

from dotenv import load_dotenv

from data.http_retry import request_with_retry

load_dotenv()

COASTAL_AIS_API_KEY = os.getenv("COASTAL_AIS_API_KEY")

# 활용신청 시 등록한 도메인. 비밀값은 아니지만(공개 저장소 주소), 신청
# 시점의 값과 반드시 일치해야 통과한다 — 바뀌면 재신청 필요.
REGISTERED_DOMAIN = "github.com/joonki1234/bluescore"

BASE_URL = "http://www.gicoms.go.kr/kodispub/openApi/wfs.do"
DEFAULT_TYPE_NAME = "lage_ship_stats_view"  # 활용가이드 샘플값 — 실제 레이어명인지 라이브로 확인 필요

REQUEST_TIMEOUT_SECONDS = 30

RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 524}  # rules_common.md 3번
MAX_RETRIES = 3
BACKOFF_SECONDS = [2, 4, 8]


class AisStatsApiError(Exception):
    """연안AIS 통계정보 API가 에러(HTTP 에러 등)를 반환했을 때 발생시키는 예외."""

    def __init__(self, message: str, status_code: Optional[int], details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _auth_params() -> dict:
    if not COASTAL_AIS_API_KEY:
        raise RuntimeError(
            "Missing COASTAL_AIS_API_KEY in environment. "
            ".env.example을 .env로 복사하고 COASTAL_AIS_API_KEY를 설정하세요."
        )
    return {"domain": REGISTERED_DOMAIN, "apikey": COASTAL_AIS_API_KEY}


def get_ais_vessel_stats_raw(type_name: str = DEFAULT_TYPE_NAME, offer_year: Optional[int] = None) -> dict:
    """WFS 오퍼레이션을 호출해 파싱 없이 원본 JSON 바디를 그대로 반환한다
    (rules_common.md 1번 — 응답 구조가 아직 미확정이라, 구조를 안다고
    전제하는 파싱/정규화 함수를 만들기 전에 원본부터 확보).

    429/5xx는 최대 3회, 2s/4s/8s 백오프 재시도한다(data/http_retry.py의
    공통 구현을 쓴다).
    """
    params = _auth_params()
    params["typeName"] = type_name
    if offer_year is not None:
        params["offeryear"] = offer_year

    response = request_with_retry(
        "GET",
        BASE_URL,
        params=params,
        retryable_status_codes=RETRYABLE_HTTP_STATUS_CODES,
        max_retries=MAX_RETRIES,
        backoff_seconds=BACKOFF_SECONDS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.ok:
        try:
            return response.json()
        except ValueError as exc:
            raise AisStatsApiError(
                "Coastal AIS stats API did not return valid JSON.",
                status_code=response.status_code,
                details=response.text[:1000],
            ) from exc

    raise AisStatsApiError(
        "Coastal AIS stats API returned an HTTP error.",
        status_code=response.status_code,
        details=response.text[:1000],
    )
