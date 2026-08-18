"""
담당: 김태윤

해양수산부 AIS 위치정보 통계 로더 (data/raw/해양수산부_AIS 위치정보 통계_20201027.TXT).
해구(고정 격자)별·시간대별 신고 선박 척수 공식 통계. score/axis_a_pressure.py의
crowding_pressure_raw 계산 보완 자료로 쓸 수 있다.

원본 파일은 EUC-KR(CP949) 인코딩이므로 UTF-8로 읽으면 깨진다.

컬럼: 해구번호, 일자, 일시(0~23시), 척수, 좌상단/우하단 경계 좌표
(전체 774,843행 중 4,646행/0.6%는 경계 결측). 데이터 기간은 2019-10-01~2020-03-31이며,
파일명의 "20201027"은 발행일일 뿐 실제 데이터 기간과 다르다.
"""

import os
from typing import Dict, List, Optional, Tuple

import pandas as pd

DEFAULT_AIS_STATS_PATH = os.path.join("data", "raw", "해양수산부_AIS 위치정보 통계_20201027.TXT")
SOURCE_ENCODING = "cp949"

_COLUMN_RENAME_MAP = {
    "해구번호": "seaGridId",
    "일자": "date",
    "일시": "hour",
    "척수": "vesselCount",
    "좌상단 경도(도)": "topLeftLon",
    "좌상단 위도(도)": "topLeftLat",
    "우하단 경도(도)": "bottomRightLon",
    "우하단 위도(도)": "bottomRightLat",
}


def load_ais_location_stats(file_path: str = DEFAULT_AIS_STATS_PATH) -> List[dict]:
    """AIS 위치정보 통계 TXT 전체를 정규화된 딕셔너리 리스트로 읽어온다.

    Returns:
        [{"seaGridId": int, "date": str, "hour": int, "vesselCount": int,
          "topLeftLon": float | None, "topLeftLat": float | None,
          "bottomRightLon": float | None, "bottomRightLat": float | None}, ...]
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(
            f"AIS 위치정보 통계 파일을 찾을 수 없습니다: {file_path}. "
            "해양수산부 공공데이터포털에서 원본 파일을 받아 해당 경로에 두세요."
        )

    df = pd.read_csv(file_path, encoding=SOURCE_ENCODING)
    df = df.rename(columns=_COLUMN_RENAME_MAP)

    # 주의: df.where(pd.notna(df), None)은 숫자형(float) 컬럼에서 None이
    # 다시 NaN으로 강제 변환돼버린다(컬럼 dtype이 float으로 고정되기 때문).
    # to_dict으로 변환한 뒤 값 단위로 pd.isna() 체크해야 실제로 None이 된다.
    records = df.to_dict(orient="records")
    return [
        {key: (None if pd.isna(value) else value) for key, value in record.items()}
        for record in records
    ]


def build_vessel_count_index(rows: List[dict]) -> Dict[Tuple[int, str, int], int]:
    """(seaGridId, date, hour) -> vesselCount 조회 인덱스를 만든다.

    774,843행 전체를 매번 순회하지 않고 상수 시간에 조회하기 위한 것이다.
    """
    return {(row["seaGridId"], row["date"], row["hour"]): row["vesselCount"] for row in rows}


def build_grid_boundary_lookup(rows: List[dict]) -> Dict[int, dict]:
    """seaGridId -> 격자 경계(topLeft/bottomRight 좌표) 조회 테이블을 만든다.

    같은 해구번호는 시점이 달라도 경계가 고정이라고 보고, 좌표가 채워진
    첫 레코드를 대표값으로 쓴다. 경계 좌표가 전부 결측인 해구는 제외된다.
    """
    lookup: Dict[int, dict] = {}
    for row in rows:
        grid_id = row["seaGridId"]
        if grid_id in lookup or row["topLeftLon"] is None:
            continue
        lookup[grid_id] = {
            "topLeftLon": row["topLeftLon"],
            "topLeftLat": row["topLeftLat"],
            "bottomRightLon": row["bottomRightLon"],
            "bottomRightLat": row["bottomRightLat"],
        }
    return lookup
