"""
담당: 김준기, 오동규

해양수산부_선박위치정보(연안AIS) 통계정보 서비스 (공공데이터포털, data.go.kr/data/15084033)
클라이언트.

연안 AIS 기반으로 1시간 단위 해양구역별 선박 척수 통계를 제공하는 XML OpenAPI다.
data/gfw_client.py와 동일하게 requests 기반 함수형 스타일로 작성했다.

주의 (공공데이터포털 서비스키):
    data/vessel_spec_client.py와 동일하게, .env의 COASTAL_AIS_API_KEY에는 반드시
    공공데이터포털에서 발급한 "Decoding" 인증키를 넣어야 한다 (Encoding 키를 넣으면
    requests가 이중 인코딩해 인증 오류가 난다).

TODO(김태윤): 아래는 아직 실제 API 명세로 검증되지 않은 잠정 스켈레톤이다.
    - BASE_URL / OPERATION_PATH: 활용신청 상세 페이지의 End Point/Operation명으로
      교체 확인 필요 (data/TODO.md 참고).
    - 요청 파라미터명(기준일자/기준시각/해역코드 등)과 응답 XML의 item 필드명은
      활용가이드 문서를 보고 확정해야 한다.
"""

import os
from typing import Dict, List, Optional
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

load_dotenv()

COASTAL_AIS_API_KEY = os.getenv("COASTAL_AIS_API_KEY")

# TODO(김태윤): 실제 End Point로 교체 필요 (data.go.kr/data/15084033 활용신청 상세 참고)
BASE_URL = "https://apis.data.go.kr/1192000/CoastalAisStatsService"
OPERATION_PATH = "/getVesselCountBySeaArea"  # TODO(김태윤): 정확한 오퍼레이션명 확인 필요

REQUEST_TIMEOUT_SECONDS = 30


class AisStatsApiError(Exception):
    """연안AIS 통계정보 API가 에러(HTTP 에러 또는 resultCode != 00)를 반환했을 때 발생시키는 예외."""

    def __init__(self, message: str, status_code: int, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _auth_params() -> dict:
    if not COASTAL_AIS_API_KEY:
        raise RuntimeError(
            "Missing COASTAL_AIS_API_KEY in environment. "
            ".env.example을 .env로 복사하고 COASTAL_AIS_API_KEY(Decoding 키)를 설정하세요."
        )
    return {"serviceKey": COASTAL_AIS_API_KEY}


def _element_to_dict(item_element: ElementTree.Element) -> Dict[str, Optional[str]]:
    """<item> 엘리먼트의 자식 태그들을 {태그명: 텍스트} 딕셔너리로 변환한다."""
    return {child.tag: child.text for child in item_element}


def _parse_xml_response(xml_text: str) -> List[Dict[str, Optional[str]]]:
    """
    공공데이터포털 표준 XML 응답(response/header/body/items/item)을 파싱해
    item 딕셔너리 리스트로 반환한다.

    resultCode가 "00"(정상)이 아니면 AisStatsApiError를 발생시킨다.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise AisStatsApiError(
            "Failed to parse coastal AIS stats API XML response.", status_code=502, details=str(exc)
        ) from exc

    result_code = root.findtext("header/resultCode") or root.findtext("cmmMsgHeader/returnReasonCode")
    result_msg = root.findtext("header/resultMsg") or root.findtext("cmmMsgHeader/returnAuthMsg")

    if result_code is not None and result_code != "00":
        raise AisStatsApiError(
            f"Coastal AIS stats API returned an error: {result_msg}",
            status_code=502,
            details={"resultCode": result_code, "resultMsg": result_msg},
        )

    items = root.findall("body/items/item")
    return [_element_to_dict(item) for item in items]


def _normalize_ais_stat(item: Dict[str, Optional[str]]) -> dict:
    """item 딕셔너리를 내부 표준 형태로 정규화한다.

    TODO(김태윤): 실제 XML 필드명 확정 후 아래 매핑을 교체할 것. 지금은 흔히 쓰이는
    필드명(기준일자/기준시각/해역명/척수 등)을 추정해 넣어둔 잠정값이다.
    """
    return {
        "baseDate": item.get("baseDe") or item.get("baseDate"),
        "baseTime": item.get("baseTm") or item.get("baseTime"),
        "seaAreaCode": item.get("seaAreaCd") or item.get("seaAreaCode"),
        "seaAreaName": item.get("seaAreaNm") or item.get("seaAreaName"),
        "vesselCount": item.get("vslCnt") or item.get("vesselCnt"),
        "raw": item,
    }


def get_ais_vessel_counts(
    base_date: str,
    base_time: str,
    sea_area_code: Optional[str] = None,
    page_no: int = 1,
    num_of_rows: int = 100,
) -> List[dict]:
    """
    기준일자·기준시각(1시간 단위)의 해양구역별 선박 척수 통계를 조회한다.

    Args:
        base_date: 기준일자, "YYYYMMDD" 형식 문자열.
        base_time: 기준시각, "HH00" 형식 문자열 (1시간 단위).
        sea_area_code: 특정 해양구역으로 좁히고 싶을 때 지정 (TODO(김태윤): 코드 체계 확인 필요).

    Returns:
        정규화된 해역별 선박 척수 통계 딕셔너리 리스트.
    """
    base_date = (base_date or "").strip()
    base_time = (base_time or "").strip()

    if not base_date or not base_time:
        raise ValueError("base_date와 base_time은 모두 필요합니다.")

    params = _auth_params()
    params["pageNo"] = page_no
    params["numOfRows"] = num_of_rows
    params["baseDe"] = base_date  # TODO(김태윤): 실제 파라미터명 확인 필요
    params["baseTm"] = base_time  # TODO(김태윤): 실제 파라미터명 확인 필요
    if sea_area_code:
        params["seaAreaCd"] = sea_area_code  # TODO(김태윤): 실제 파라미터명 확인 필요

    response = requests.get(
        f"{BASE_URL}{OPERATION_PATH}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        raise AisStatsApiError(
            "Coastal AIS stats API returned an HTTP error.",
            status_code=response.status_code,
            details=response.text,
        )

    items = _parse_xml_response(response.text)
    return [_normalize_ais_stat(item) for item in items]
