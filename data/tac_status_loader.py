"""
담당: 김준기, 오동규

한국수산자원공단_TAC(총허용어획량) 어종별 소진현황 로더
(공공데이터포털, data.go.kr/data/15127264).

이 데이터셋은 API가 아니라 XLSX 파일로만 배포된다. 따라서 여기서는 로컬에 미리
받아둔 엑셀 파일 경로를 읽어 pandas로 파싱하는 함수만 제공한다 (인증키 불필요).

TODO(김태윤): 아래는 아직 실제 파일 스키마로 검증되지 않은 잠정 스켈레톤이다.
    - 실제 다운로드한 data/raw/tac_status.xlsx의 시트명/헤더 행 위치/컬럼명을
      확인한 뒤 EXPECTED_COLUMNS와 _normalize_row()의 매핑을 교체해야 한다
      (data/TODO.md 참고).
"""

import os
from typing import List, Optional

import pandas as pd

# 로컬에 미리 받아둔 TAC 소진현황 엑셀 파일의 기본 경로.
DEFAULT_TAC_STATUS_PATH = os.path.join("data", "raw", "tac_status.xlsx")

# TODO(김태윤): 실제 파일의 컬럼명 확인 후 교체 필요. 지금은 흔히 쓰이는 컬럼명을
# 추정해 넣어둔 잠정값이다.
EXPECTED_COLUMNS = ["어종명", "관리해역", "TAC배정량", "소진량", "소진율"]


def _normalize_row(row: dict) -> dict:
    """엑셀 한 행(dict)을 내부 표준 형태로 정규화한다.

    TODO(김태윤): 실제 컬럼명 확정 후 아래 매핑을 교체할 것.
    """
    return {
        "speciesName": row.get("어종명"),
        "managedSeaArea": row.get("관리해역"),
        "tacQuotaTon": row.get("TAC배정량"),
        "consumedTon": row.get("소진량"),
        "consumptionRatio": row.get("소진율"),
        "raw": row,
    }


def load_tac_status(
    file_path: str = DEFAULT_TAC_STATUS_PATH,
    sheet_name: Optional[str] = 0,
) -> List[dict]:
    """
    로컬 TAC 소진현황 XLSX 파일을 읽어 정규화된 딕셔너리 리스트로 반환한다.

    Args:
        file_path: TAC 소진현황 엑셀 파일 경로 (기본값: data/raw/tac_status.xlsx).
        sheet_name: pandas.read_excel에 넘길 시트명/인덱스 (기본값: 첫 번째 시트).

    Returns:
        정규화된 어종별 TAC 소진현황 딕셔너리 리스트.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(
            f"TAC 소진현황 파일을 찾을 수 없습니다: {file_path}. "
            "공공데이터포털(data.go.kr/data/15127264)에서 XLSX를 내려받아 해당 경로에 두세요."
        )

    df = pd.read_excel(file_path, sheet_name=sheet_name)
    rows = df.to_dict(orient="records")
    return [_normalize_row(row) for row in rows]
