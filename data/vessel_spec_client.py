"""
담당: 김준기, 오동규

해양수산부_선박제원정보 서비스 (공공데이터포털, data.go.kr/data/15055851) 클라이언트.

XML 응답을 반환하는 공공데이터포털 OpenAPI로, 선박 식별자(MMSI/선박명 등)로
선박의 톤수·길이·너비·어업종 등 제원 정보를 조회한다. data/gfw_client.py와 동일하게
requests 기반 함수형 스타일로 작성했다.

주의 (공공데이터포털 서비스키):
    공공데이터포털은 신청 시 "인증키(Encoding)"와 "인증키(Decoding)" 두 가지를 함께
    발급한다. requests의 params=... 는 값을 자동으로 URL 인코딩하므로, 이미 인코딩된
    키를 그대로 넣으면 이중 인코딩되어 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 발생할 수
    있다. .env의 VESSEL_SPEC_API_KEY에는 반드시 "Decoding" 키를 넣어야 한다.

TODO(김태윤): 아래는 아직 실제 API 명세로 검증되지 않은 잠정 스켈레톤이다.
    - BASE_URL / OPERATION_PATH: 공공데이터포털 "선박제원정보서비스" 활용신청 상세
      페이지의 End Point/Operation명으로 교체 확인 필요 (data/TODO.md 참고).
    - REQUEST_PARAM_*, 응답 XML의 item 필드명(예: 선박명/톤수/길이 컬럼명)은 활용가이드
      문서를 보고 확정해야 한다. 지금은 흔히 쓰이는 필드명을 추정해 넣어둔 상태다.
"""

import os
from typing import Dict, List, Optional
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

load_dotenv()

VESSEL_SPEC_API_KEY = os.getenv("VESSEL_SPEC_API_KEY")

# TODO(김태윤): 실제 End Point로 교체 필요 (data.go.kr/data/15055851 활용신청 상세 참고)
BASE_URL = "https://apis.data.go.kr/1192000/VesselSpecInfoService"
OPERATION_PATH = "/getVesselSpecInfo"  # TODO(김태윤): 정확한 오퍼레이션명 확인 필요

REQUEST_TIMEOUT_SECONDS = 30


class VesselSpecApiError(Exception):
    """선박제원정보 API가 에러(HTTP 에러 또는 resultCode != 00)를 반환했을 때 발생시키는 예외."""

    def __init__(self, message: str, status_code: int, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def _auth_params() -> dict:
    if not VESSEL_SPEC_API_KEY:
        raise RuntimeError(
            "Missing VESSEL_SPEC_API_KEY in environment. "
            ".env.example을 .env로 복사하고 VESSEL_SPEC_API_KEY(Decoding 키)를 설정하세요."
        )
    return {"serviceKey": VESSEL_SPEC_API_KEY}


def _element_to_dict(item_element: ElementTree.Element) -> Dict[str, Optional[str]]:
    """<item> 엘리먼트의 자식 태그들을 {태그명: 텍스트} 딕셔너리로 변환한다."""
    return {child.tag: child.text for child in item_element}


def _parse_xml_response(xml_text: str) -> List[Dict[str, Optional[str]]]:
    """
    공공데이터포털 표준 XML 응답(response/header/body/items/item)을 파싱해
    item 딕셔너리 리스트로 반환한다.

    resultCode가 "00"(정상)이 아니면 VesselSpecApiError를 발생시킨다.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise VesselSpecApiError(
            "Failed to parse vessel spec API XML response.", status_code=502, details=str(exc)
        ) from exc

    result_code = root.findtext("header/resultCode") or root.findtext("cmmMsgHeader/returnReasonCode")
    result_msg = root.findtext("header/resultMsg") or root.findtext("cmmMsgHeader/returnAuthMsg")

    if result_code is not None and result_code != "00":
        raise VesselSpecApiError(
            f"Vessel spec API returned an error: {result_msg}",
            status_code=502,
            details={"resultCode": result_code, "resultMsg": result_msg},
        )

    items = root.findall("body/items/item")
    return [_element_to_dict(item) for item in items]


def _normalize_vessel_spec(item: Dict[str, Optional[str]]) -> dict:
    """item 딕셔너리를 내부 표준 형태로 정규화한다.

    TODO(김태윤): 실제 XML 필드명 확정 후 아래 매핑을 교체할 것. 지금은 흔히 쓰이는
    필드명(선박명/톤수/길이/너비/MMSI 등)을 추정해 넣어둔 잠정값이다.
    """
    return {
        "vesselName": item.get("vesselNm") or item.get("shipNm"),
        "mmsi": item.get("mmsi"),
        "tonnage": item.get("tonMg") or item.get("grossTonnage"),
        "length": item.get("lenGtWid") or item.get("length"),
        "width": item.get("width"),
        "fishingType": item.get("fishBusiSeCd") or item.get("fishingType"),
        "raw": item,
    }


def search_vessel_spec(
    vessel_name: Optional[str] = None,
    mmsi: Optional[str] = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> List[dict]:
    """
    선박명 또는 MMSI로 선박제원정보를 조회한다.

    vessel_name, mmsi 중 최소 하나는 지정해야 한다.

    Returns:
        정규화된 선박제원 딕셔너리 리스트.
    """
    vessel_name = (vessel_name or "").strip()
    mmsi = (mmsi or "").strip()

    if not vessel_name and not mmsi:
        raise ValueError("vessel_name 또는 mmsi 중 하나는 필요합니다.")

    params = _auth_params()
    params["pageNo"] = page_no
    params["numOfRows"] = num_of_rows
    if vessel_name:
        params["vesselNm"] = vessel_name  # TODO(김태윤): 실제 파라미터명 확인 필요
    if mmsi:
        params["mmsi"] = mmsi  # TODO(김태윤): 실제 파라미터명 확인 필요

    response = requests.get(
        f"{BASE_URL}{OPERATION_PATH}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if not response.ok:
        raise VesselSpecApiError(
            "Vessel spec API returned an HTTP error.",
            status_code=response.status_code,
            details=response.text,
        )

    items = _parse_xml_response(response.text)
    return [_normalize_vessel_spec(item) for item in items]
