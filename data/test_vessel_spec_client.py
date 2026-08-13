"""
담당: 김준기, 오동규

data/vessel_spec_client.py 단위 테스트. 2026-08-13에 실제 API(vsslNm=케미)로
호출해 받은 응답 일부를 고정 XML로 박아넣어(mock) 파싱/정규화 로직을 검증한다.
"""

from unittest.mock import Mock, patch

import pytest

from data.vessel_spec_client import (
    VesselSpecApiError,
    _normalize_vessel_spec,
    _parse_xml_response,
    _to_float,
    search_vessel_spec,
)

SAMPLE_SUCCESS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    "<response><header><resultCode>00</resultCode><resultMsg>NORMAL_SERVICE</resultMsg></header>"
    "<body><items>"
    "<item><ibobprt>[]</ibobprt><clsgn>010641</clsgn><vsslNo>010641</vsslNo><imoNo>8303965</imoNo>"
    "<vsslKorNm>블루케미호</vsslKorNm><vsslEngNm></vsslEngNm><vsslKnd>53[케미칼 운반선]</vsslKnd>"
    "<vsslNlty>KR[대한민국]</vsslNlty><tonEdycSe></tonEdycSe><tonEdycSeNm></tonEdycSeNm>"
    "<intrlGrtg></intrlGrtg><grtg>4151</grtg><ntng></ntng><vsslTotLt></vsslTotLt><shdth>17.2</shdth>"
    "<vsslDrft></vsslDrft><vsslLt>98.07</vsslLt><vsslDp>9.2</vsslDp><brbtSe></brbtSe><brbtSeNm></brbtSeNm>"
    "<nvgShapCd></nvgShapCd><nvgShapNm>-</nvgShapNm><vsslCnstrDt>1983-02-26T00:00:00+09:00</vsslCnstrDt>"
    "<befClsgn></befClsgn><nwshipAt>N</nwshipAt></item>"
    "<item><ibobprt>2[내항]</ibobprt><clsgn>021568</clsgn><vsslNo>021568</vsslNo><imoNo>9186467</imoNo>"
    "<vsslKorNm>101효동케미호</vsslKorNm><vsslEngNm>101 HYODONG CHEMI</vsslEngNm>"
    "<vsslKnd>52[석유제품 운반선]</vsslKnd><vsslNlty>KR[대한민국]</vsslNlty><tonEdycSe>2</tonEdycSe>"
    "<tonEdycSeNm>국적증서</tonEdycSeNm><intrlGrtg>0</intrlGrtg><grtg>2204</grtg><ntng>977</ntng>"
    "<vsslTotLt>85</vsslTotLt><shdth>14.4</shdth><vsslDrft>4</vsslDrft><vsslLt>82.53</vsslLt>"
    "<vsslDp>6.9</vsslDp><brbtSe>9</brbtSe><brbtSeNm>기타용선</brbtSeNm><nvgShapCd>2</nvgShapCd>"
    "<nvgShapNm>부정기선</nvgShapNm><vsslCnstrDt>1998-02-19T00:00:00+09:00</vsslCnstrDt>"
    "<befClsgn>DSNA8</befClsgn><nwshipAt>N</nwshipAt></item>"
    "</items></body></response>"
)

SAMPLE_ERROR_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<response><header><resultCode>99</resultCode><resultMsg>UNKNOWN_ERROR</resultMsg></header></response>"
)


class TestToFloat:
    def test_empty_string_returns_none(self):
        assert _to_float("") is None

    def test_none_returns_none(self):
        assert _to_float(None) is None

    def test_valid_number_string_converts(self):
        assert _to_float("82.53") == 82.53


class TestParseXmlResponse:
    def test_parses_items_from_real_sample(self):
        items = _parse_xml_response(SAMPLE_SUCCESS_XML)

        assert len(items) == 2
        assert items[1]["clsgn"] == "021568"

    def test_error_result_code_raises(self):
        with pytest.raises(VesselSpecApiError):
            _parse_xml_response(SAMPLE_ERROR_XML)

    def test_malformed_xml_raises(self):
        with pytest.raises(VesselSpecApiError):
            _parse_xml_response("not xml")


class TestNormalizeVesselSpec:
    def test_maps_real_fields_correctly(self):
        items = _parse_xml_response(SAMPLE_SUCCESS_XML)
        normalized = _normalize_vessel_spec(items[1])

        assert normalized["vesselNameKor"] == "101효동케미호"
        assert normalized["vesselNameEng"] == "101 HYODONG CHEMI"
        assert normalized["callSign"] == "021568"
        assert normalized["imoNo"] == "9186467"
        assert normalized["grossTonnage"] == 2204.0
        assert normalized["lengthM"] == 82.53
        assert normalized["widthM"] == 14.4

    def test_blank_numeric_fields_become_none(self):
        items = _parse_xml_response(SAMPLE_SUCCESS_XML)
        normalized = _normalize_vessel_spec(items[0])  # 블루케미호: ntng/vsslTotLt 등이 실제로 빈 값

        assert normalized["netTonnage"] is None
        assert normalized["totalLengthM"] is None
        assert normalized["vesselNameEng"] is None


class TestSearchVesselSpec:
    def test_raises_when_no_search_term_given(self):
        with pytest.raises(ValueError):
            search_vessel_spec()

    @patch("data.vessel_spec_client.requests.get")
    @patch("data.vessel_spec_client.VESSEL_SPEC_API_KEY", "dummy-key")
    def test_returns_normalized_results_on_success(self, mock_get):
        mock_get.return_value = Mock(ok=True, text=SAMPLE_SUCCESS_XML)

        results = search_vessel_spec(vessel_name="케미")

        assert len(results) == 2
        assert results[0]["vesselNameKor"] == "블루케미호"

    @patch("data.vessel_spec_client.requests.get")
    @patch("data.vessel_spec_client.VESSEL_SPEC_API_KEY", "dummy-key")
    def test_sends_call_sign_param(self, mock_get):
        mock_get.return_value = Mock(ok=True, text=SAMPLE_SUCCESS_XML)

        search_vessel_spec(call_sign="3EKR5")

        _, kwargs = mock_get.call_args
        assert kwargs["params"]["clsgn"] == "3EKR5"
        assert "vsslNm" not in kwargs["params"]
