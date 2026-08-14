"""
담당: 김태윤

해양수산부 수산정보 어업별어선(업종별 척수·톤수·마력) 로더
(data/raw/해양수산부_수산정보_MR 어업별어선_20240910.csv).

기획서 8-3번 데이터 목록에 "해양수산부 수산정보 어업별어선 - 어업종별
척수·총톤수·총마력. 개별 선박 엔진출력이 없는 경우 업종별 총마력을
보정값으로 활용"이라고 명시된 파일이다.

원본 파일은 EUC-KR(CP949) 인코딩이고, 업종명(컬럼 명) 문자열에 원본 문서의
고정폭 정렬 흔적으로 보이는 공백이 글자 사이마다 섞여 있다(예:
"- 근  해   채  낚  기   어  업"). 이 로더는 그 내부 공백을 제거해 정규화한
업종명(gearTypeName)을 반환한다.

파일 구조 (2026-08-14, 직접 열어서 확인):
    컬럼: 통계 년도, 통계 코드, 컬럼 명(업종명, 공백 섞임), 컬럼 영문명,
          전체 척 수, 전체 톤수, 전체 마력, 동력 척 수, 동력 톤수, 동력 마력,
          무동력 척 수, 무동력 톤수, 최초 생성 시점, 최종 변경 시점
    - 통계년도: 1992~2020 (연속 아님 — 1995/1996/2010/2012 등 결측 연도 있음)
    - 정규화한 업종명 고유 102개. "총계"/"근해어업"/"원양어업" 같은 상위
      집계 행과 "대형기선 저인망 어업(외끌이)" 같은 세부 업종 행이 섞여
      있고, 원본에서 세부 업종명 앞에 "-"가 붙어 있다. 이 로더는 그 "-"
      유무로 isSubCategory만 표시하고, 계층 구조를 트리로 엄밀히 파싱하지는
      않는다 — 필요해지면 추가 작업 필요.
    - 무동력 선박에는 마력 컬럼이 없다(엔진이 없으므로).
    - 마력 단위 표기가 원본에 없다 (data/TODO.md "기관출력 단위(HP/PS) 확인"
      항목 참고 — 아직 미확인).

주의: 국내 업종 분류(이 파일의 gearTypeName)를 GFW의 gear type으로 매핑하는
작업은 아직 담당이 정해지지 않았고, 도메인 판단이 필요해 팀 논의로 확정해야
한다(자동화 불가). 이 로더는 그 매핑을 만들지 않는다.
"""

import os
import re
from typing import List, Optional

import pandas as pd

DEFAULT_FISHERY_VESSEL_STATS_PATH = os.path.join(
    "data", "raw", "해양수산부_수산정보_MR 어업별어선_20240910.csv"
)
SOURCE_ENCODING = "cp949"

_COLUMN_RENAME_MAP = {
    "통계 년도": "year",
    "통계 코드": "statCode",
    "컬럼 영문명": "gearTypeNameEn",
    "전체 척 수": "totalVesselCount",
    "전체 톤수": "totalTonnage",
    "전체 마력": "totalHorsepower",
    "동력 척 수": "poweredVesselCount",
    "동력 톤수": "poweredTonnage",
    "동력 마력": "poweredHorsepower",
    "무동력 척 수": "unpoweredVesselCount",
    "무동력 톤수": "unpoweredTonnage",
}


def _normalize_gear_type_name(raw_name: str) -> str:
    """업종명 문자열 내부의 (고정폭 정렬용) 공백을 전부 제거한다."""
    return re.sub(r"\s+", "", raw_name)


def load_fishery_vessel_stats(
    file_path: str = DEFAULT_FISHERY_VESSEL_STATS_PATH,
) -> List[dict]:
    """어업별어선 통계 CSV 전체를 정규화된 딕셔너리 리스트로 읽어온다.

    Returns:
        [{"year": int, "statCode": int, "gearTypeName": str,
          "gearTypeNameEn": str, "totalVesselCount": float,
          "totalTonnage": float, "totalHorsepower": float,
          "poweredVesselCount": float, "poweredTonnage": float,
          "poweredHorsepower": float, "unpoweredVesselCount": float,
          "unpoweredTonnage": float, "isSubCategory": bool, "raw": dict}, ...]
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(
            f"어업별어선 통계 파일을 찾을 수 없습니다: {file_path}. "
            "해양수산부 공공데이터포털에서 원본 파일을 받아 해당 경로에 두세요."
        )

    df = pd.read_csv(file_path, encoding=SOURCE_ENCODING)

    rows = []
    for raw_record in df.to_dict(orient="records"):
        # 주의: df.where(pd.notna(df), None)은 숫자형(float) 컬럼에서 None이
        # 다시 NaN으로 강제 변환돼버린다(컬럼 dtype이 float으로 고정되기
        # 때문). 값 단위로 pd.isna() 체크해야 실제로 None이 된다.
        record = {key: (None if pd.isna(value) else value) for key, value in raw_record.items()}
        raw_name = record["컬럼 명"]
        normalized = {new_key: record[old_key] for old_key, new_key in _COLUMN_RENAME_MAP.items()}
        normalized["gearTypeName"] = _normalize_gear_type_name(raw_name)
        normalized["isSubCategory"] = raw_name.strip().startswith("-")
        normalized["raw"] = record
        rows.append(normalized)

    return rows


def get_gear_type_stats(rows: List[dict], gear_type_name: str, year: int) -> Optional[dict]:
    """정규화된 업종명 + 연도로 통계 한 건을 조회한다. 없으면 None."""
    for row in rows:
        if row["gearTypeName"] == gear_type_name and row["year"] == year:
            return row
    return None


def list_gear_type_names(rows: List[dict]) -> List[str]:
    """데이터에 등장하는 정규화된 업종명 전체(중복 제거, 정렬)를 반환한다."""
    return sorted({row["gearTypeName"] for row in rows})
