"""
담당: 김준기, 오동규

한국수산자원공단_TAC(총허용어획량) 어종별 소진현황 로더
(공공데이터포털, data.go.kr/data/15127264).

이 데이터셋은 API가 아니라 XLSX 파일로만 배포된다. data/raw/tac_status.xlsx를
pandas로 읽어 정규화된 딕셔너리 리스트로 반환한다 (인증키 불필요).

실제 파일 구조 (2026-08-13, 오동규가 data/raw/tac_status.xlsx를 직접 열어 확인):
    - 시트가 24개이며, 어종별이 아니라 연도/기간별로 나뉜다
      ("2000년 1~12월" ~ "2023년 7월~2024년 2월 5주"). 마지막 시트가 가장 최근 기간이다.
    - "관리해역" 컬럼은 존재하지 않는다 (이전 버전의 잘못된 추정이었음).
    - 각 시트는 다중 행 헤더 + 어종×업종 계층 구조다. 컬럼 0=어종명(병합 셀,
      forward-fill 필요), 컬럼 1=업종(또는 "합계"/"계" 같은 어종 소계 라벨).
    - 오래된 시트는 5컬럼(어종/업종/배분량/어획량/소진율), 최신 시트는 10컬럼
      (어종/업종/대상어선/배분량×2기간/소진량×2기간/증감율/소진율×2기간)처럼
      컬럼 수와 배치가 시트마다 다르다. 그래서 컬럼 위치가 아니라 헤더 텍스트의
      키워드로 나머지 컬럼을 분류한다.

주의:
    - 헤더/데이터 경계는 "합계" 텍스트가 아니라 "수치 컬럼에 처음으로 숫자값이
      나타나는 행"으로 판단한다 (_find_data_start_row 참고). 최신 시트의 전체
      합계 행은 "합계"가 아니라 "15종"으로 표기되어 있어 텍스트 매칭이
      신뢰할 수 없었기 때문이다.
    - 동일 카테고리(예: 소진율)에 해당하는 컬럼이 여러 개(당해/전년 비교)면 가장
      왼쪽(최근 기간) 값만 정규화된 필드에 채택한다. 나머지는 raw에 전부 보존된다.
    - 24개 시트 전부를 개별 검증하지는 못했다. 5컬럼/10컬럼 두 가지 실제 확인된
      레이아웃을 기준으로 일반화한 파서이며, 다른 레이아웃의 시트가 있다면
      _classify_column()의 키워드 매칭이 깨질 수 있다.
"""

import os
from typing import Dict, List, Optional

import pandas as pd

# 로컬에 미리 받아둔 TAC 소진현황 엑셀 파일의 기본 경로.
DEFAULT_TAC_STATUS_PATH = os.path.join("data", "raw", "tac_status.xlsx")

# 데이터 시작 행을 찾기 위해 훑어볼 최대 행 수 (헤더 영역이 이보다 길면 못 찾음)
HEADER_SEARCH_MAX_ROWS = 8

# 헤더 라벨 텍스트에 포함된 키워드로 컬럼을 분류한다. "소진율"/"소진량"처럼 접두어가
# 같은 키워드가 있어 순서가 중요하다.
_VESSEL_COUNT_KEYWORDS = ("대상어선", "척수")
_RATIO_KEYWORDS = ("소진율",)
_CHANGE_KEYWORDS = ("증감율",)
_ALLOCATION_KEYWORDS = ("배분량",)
_CONSUMED_KEYWORDS = ("소진량", "어획량")


def _find_data_start_row(raw: pd.DataFrame) -> int:
    """헤더 영역이 끝나고 실제 데이터가 시작하는 행 인덱스를 찾는다.

    헤더 행에는 라벨 텍스트만 있고 숫자가 없다는 점을 이용해, 어종/업종
    컬럼(0, 1)을 제외한 수치 컬럼 중 하나라도 숫자값이 처음 나타나는 행을
    데이터 시작으로 판단한다.
    """
    search_rows = min(HEADER_SEARCH_MAX_ROWS, len(raw))
    value_columns = raw.columns[2:]

    for row_idx in range(search_rows):
        row = raw.iloc[row_idx]
        if any(isinstance(row[col], (int, float)) and not pd.isna(row[col]) for col in value_columns):
            return row_idx

    raise ValueError(f"수치 데이터가 시작하는 행을 찾지 못했습니다 (첫 {search_rows}행 탐색).")


def _build_column_labels(raw: pd.DataFrame, data_start_row: int) -> List[str]:
    """데이터 시작 행 이전(헤더 영역)의 셀 텍스트를 컬럼별로 이어붙여 라벨을 만든다."""
    header_rows = raw.iloc[:data_start_row]
    labels = []
    for col in raw.columns:
        parts = [str(value).strip() for value in header_rows[col] if isinstance(value, str) and value.strip()]
        labels.append(" ".join(parts))
    return labels


def _classify_column(label: str) -> Optional[str]:
    """헤더 라벨 텍스트를 정규화 필드 이름으로 분류한다. 매칭 안 되면 None."""
    if any(keyword in label for keyword in _VESSEL_COUNT_KEYWORDS):
        return "vesselCount"
    if any(keyword in label for keyword in _RATIO_KEYWORDS):
        return "consumptionRatioPercent"
    if any(keyword in label for keyword in _CHANGE_KEYWORDS):
        return "changeRatePercent"
    if any(keyword in label for keyword in _ALLOCATION_KEYWORDS):
        return "allocationTon"
    if any(keyword in label for keyword in _CONSUMED_KEYWORDS):
        return "consumedTon"
    return None


def list_available_periods(file_path: str = DEFAULT_TAC_STATUS_PATH) -> List[str]:
    """워크북에 있는 전체 기간(시트명) 목록을 순서대로 반환한다. 마지막 항목이 최신 기간이다."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(
            f"TAC 소진현황 파일을 찾을 수 없습니다: {file_path}. "
            "공공데이터포털(data.go.kr/data/15127264)에서 XLSX를 내려받아 해당 경로에 두세요."
        )
    return pd.ExcelFile(file_path).sheet_names


def load_tac_status(
    file_path: str = DEFAULT_TAC_STATUS_PATH,
    sheet_name: Optional[str] = None,
) -> List[dict]:
    """
    로컬 TAC 소진현황 XLSX 파일의 한 기간(시트)을 읽어 정규화된 딕셔너리 리스트로 반환한다.

    Args:
        file_path: TAC 소진현황 엑셀 파일 경로 (기본값: data/raw/tac_status.xlsx).
        sheet_name: 읽을 기간(시트명). None이면 워크북의 마지막 시트(가장 최근 기간)를
            사용한다. list_available_periods()로 전체 기간 목록을 확인할 수 있다.

    Returns:
        정규화된 어종×업종별 TAC 소진현황 딕셔너리 리스트. 각 항목은 speciesName,
        gearType, vesselCount, allocationTon, consumedTon, consumptionRatioPercent,
        changeRatePercent, periodLabel, raw 키를 가진다.
    """
    periods = list_available_periods(file_path)  # 파일 존재 확인도 겸함

    if sheet_name is None:
        sheet_name = periods[-1]

    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    data_start_row = _find_data_start_row(raw)
    column_labels = _build_column_labels(raw, data_start_row)

    data = raw.iloc[data_start_row:].reset_index(drop=True)
    data[0] = data[0].ffill()

    rows: List[dict] = []
    for _, row in data.iterrows():
        species_name = None if pd.isna(row[0]) else str(row[0]).strip()
        gear_type = None if pd.isna(row[1]) else str(row[1]).strip()

        if species_name is None and gear_type is None and row.iloc[2:].isna().all():
            continue  # 완전 빈 행 스킵

        classified: Dict[str, object] = {}
        for col_index in range(2, len(column_labels)):
            category = _classify_column(column_labels[col_index])
            if category is None or category in classified:
                continue
            value = row[col_index]
            classified[category] = None if pd.isna(value) else value

        raw_row = {
            (column_labels[i] or f"col{i}"): (None if pd.isna(row[i]) else row[i])
            for i in range(len(column_labels))
        }

        rows.append(
            {
                "speciesName": species_name,
                "gearType": gear_type,
                "vesselCount": classified.get("vesselCount"),
                "allocationTon": classified.get("allocationTon"),
                "consumedTon": classified.get("consumedTon"),
                "consumptionRatioPercent": classified.get("consumptionRatioPercent"),
                "changeRatePercent": classified.get("changeRatePercent"),
                "periodLabel": sheet_name,
                "raw": raw_row,
            }
        )

    return rows
