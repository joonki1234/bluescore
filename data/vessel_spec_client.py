"""
담당: 김준기, 오동규

해양수산부_선박제원정보 서비스 (공공데이터포털, data.go.kr/data/15055851) 클라이언트.

XML 응답을 반환하는 공공데이터포털 OpenAPI로, 선박명 또는 호출부호(콜사인)로
선박의 톤수·길이·너비 등 제원 정보를 조회한다. data/gfw_client.py와 동일하게
requests 기반 함수형 스타일로 작성했다.

실제 API 검증 완료 (2026-08-13, 오동규가 실제 발급받은 키로 호출해 확인):
    - End Point: https://apis.data.go.kr/1192000/SicsVsslManp3/Info3
      (data.go.kr 활용신청 상세 페이지의 "① 선박제원정보 조회 /Info3" 오퍼레이션.
      이전 버전 코드에 있던 VesselSpecInfoService/getVesselSpecInfo는 잘못된
      추측이었고, 호출 시 NO_OPENAPI_SERVICE_ERROR가 발생했다.)
    - 요청 파라미터: serviceKey, pageNo, numOfRows(최대 50), vsslNm(검색할 선박명),
      clsgn(검색할 호출부호). vsslNm/clsgn 중 최소 하나로 검색해야 한다.
    - **MMSI로 검색하는 파라미터는 이 API에 없다.** 응답 필드에도 MMSI가 없고,
      식별자는 clsgn(호출부호)/vsslNo(선박번호)/imoNo(IMO번호)뿐이다. 즉 GFW의
      mmsi/ssvid와 이 API 결과를 직접 매칭할 수 없다 — data/TODO.md의 "선박 매칭
      실사(exact/fuzzy)"는 선박명 유사도 매칭 위주로 가야 할 가능성이 높다.
      김태윤 확인 필요.
    - 응답에 어업종(저인망/통발 등 수산업법상 분류) 필드가 없다. vsslKnd(선종)는
      "53[케미칼 운반선]"처럼 일반 선박 종류 코드다. "케미"로 검색했을 때 화학
      운반선들이 나온 걸 보면 이 API는 어선 전용이 아니라 등록된 선박 전체를
      대상으로 한다. 어업종 정보는 기획서에 별도로 언급된 "해양수산부 수산정보
      어업별어선"(파일 데이터셋)에서 가져와야 할 수 있다.

응답 구조 (실제 확인, response/header/resultCode·resultMsg, response/body/items/item):
    <response>
      <header><resultCode>00</resultCode><resultMsg>NORMAL_SERVICE</resultMsg></header>
      <body><items><item>
        <clsgn>021568</clsgn> <vsslNo>021568</vsslNo> <imoNo>9186467</imoNo>
        <vsslKorNm>101효동케미호</vsslKorNm> <vsslEngNm>101 HYODONG CHEMI</vsslEngNm>
        <vsslKnd>52[석유제품 운반선]</vsslKnd> <vsslNlty>KR[대한민국]</vsslNlty>
        <grtg>2204</grtg> <ntng>977</ntng> <intrlGrtg>0</intrlGrtg>
        <vsslLt>82.53</vsslLt> <vsslTotLt>85</vsslTotLt> <shdth>14.4</shdth>
        <vsslDp>6.9</vsslDp> <vsslDrft>4</vsslDrft>
        <vsslCnstrDt>1998-02-19T00:00:00+09:00</vsslCnstrDt> <nwshipAt>N</nwshipAt>
        ...
      </item></items></body>
    </response>

주의 (공공데이터포털 서비스키):
    공공데이터포털은 신청 시 "인증키(Encoding)"와 "인증키(Decoding)" 두 가지를 함께
    발급한다. requests의 params=... 는 값을 자동으로 URL 인코딩하므로, 이미 인코딩된
    키를 그대로 넣으면 이중 인코딩되어 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 발생할 수
    있다. .env의 VESSEL_SPEC_API_KEY에는 반드시 "Decoding" 키를 넣어야 한다.
"""

import os
from typing import Dict, List, Optional
from xml.etree import ElementTree

import requests
from dotenv import load_dotenv

load_dotenv()

VESSEL_SPEC_API_KEY = os.getenv("VESSEL_SPEC_API_KEY")

BASE_URL = "https://apis.data.go.kr/1192000/SicsVsslManp3"
OPERATION_PATH = "/Info3"

REQUEST_TIMEOUT_SECONDS = 30
MAX_NUM_OF_ROWS = 50  # data.go.kr 활용신청 페이지에 명시된 조회 결과 최대 개수


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


def _to_float(value: Optional[str]) -> Optional[float]:
    """공공데이터포털 응답의 숫자 필드는 문자열이며, 값이 없으면 빈 문자열("")로 온다."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _element_to_dict(item_element) -> Dict[str, Optional[str]]:
    """<item> 엘리먼트의 자식 태그들을 {태그명: 텍스트} 딕셔너리로 변환한다."""
    return {child.tag: child.text for child in item_element}


def _parse_xml_response(xml_text: str) -> List[Dict[str, Optional[str]]]:
    """
    선박제원정보 API의 XML 응답(response/header/body/items/item)을 파싱해
    item 딕셔너리 리스트로 반환한다.

    resultCode가 "00"(정상)이 아니면 VesselSpecApiError를 발생시킨다.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise VesselSpecApiError(
            "Failed to parse vessel spec API XML response.", status_code=502, details=str(exc)
        ) from exc

    result_code = root.findtext("header/resultCode")
    result_msg = root.findtext("header/resultMsg")

    if result_code is not None and result_code != "00":
        raise VesselSpecApiError(
            f"Vessel spec API returned an error: {result_msg}",
            status_code=502,
            details={"resultCode": result_code, "resultMsg": result_msg},
        )

    items = root.findall("body/items/item")
    return [_element_to_dict(item) for item in items]


def _normalize_vessel_spec(item: Dict[str, Optional[str]]) -> dict:
    """item 딕셔너리를 내부 표준 형태로 정규화한다 (실제 API 응답 필드명 기준)."""
    return {
        "vesselNameKor": item.get("vsslKorNm") or None,
        "vesselNameEng": item.get("vsslEngNm") or None,
        "callSign": item.get("clsgn") or None,
        "vesselNo": item.get("vsslNo") or None,
        "imoNo": item.get("imoNo") or None,
        "vesselKind": item.get("vsslKnd") or None,  # 예: "52[석유제품 운반선]" (코드+명 결합형)
        "nationality": item.get("vsslNlty") or None,
        "grossTonnage": _to_float(item.get("grtg")),
        "netTonnage": _to_float(item.get("ntng")),
        "internationalGrossTonnage": _to_float(item.get("intrlGrtg")),
        "lengthM": _to_float(item.get("vsslLt")),
        "totalLengthM": _to_float(item.get("vsslTotLt")),
        "widthM": _to_float(item.get("shdth")),
        "depthM": _to_float(item.get("vsslDp")),
        "draftM": _to_float(item.get("vsslDrft")),
        "constructionDate": item.get("vsslCnstrDt") or None,
        "isNewShip": item.get("nwshipAt") or None,
        "raw": item,
    }


def search_vessel_spec(
    vessel_name: Optional[str] = None,
    call_sign: Optional[str] = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> List[dict]:
    """
    선박명 또는 호출부호(콜사인)로 선박제원정보를 조회한다.

    vessel_name, call_sign 중 최소 하나는 지정해야 한다. 이 API는 MMSI로 검색할
    수 없다 (모듈 docstring 참고).

    Args:
        vessel_name: 검색할 선박명 (예: "케미").
        call_sign: 검색할 호출부호 (예: "3EKR5").
        page_no: 페이지 번호.
        num_of_rows: 조회 결과 최대 개수 (API 제한 최대 50).

    Returns:
        정규화된 선박제원 딕셔너리 리스트.
    """
    vessel_name = (vessel_name or "").strip()
    call_sign = (call_sign or "").strip()

    if not vessel_name and not call_sign:
        raise ValueError("vessel_name 또는 call_sign 중 하나는 필요합니다.")

    params = _auth_params()
    params["pageNo"] = page_no
    params["numOfRows"] = num_of_rows
    if vessel_name:
        params["vsslNm"] = vessel_name
    if call_sign:
        params["clsgn"] = call_sign

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
