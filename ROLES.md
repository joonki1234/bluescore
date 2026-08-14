# ROLES.md

BlueScore 폴더/영역별 담당자 매핑.

| 폴더/영역 | 담당 |
| --- | --- |
| `data/` | 김태윤 |
| `score/` | 김준기, 오동규 |
| `chain/` | 김준기, 오동규 |
| `explain/` | 최지희 |
| `app.py`, `ui/` | 최지희 |

새 파일을 만들 때는 이 표를 기준으로 파일 상단 주석에 `담당: {이름}`을 표기한다.

> `map/`은 별도 폴더로 만들지 않고 `ui/components.py`의 지도 컴포넌트로 흡수했다.
> 지도가 점수·분포·리포트와 같은 화면 안에서만 쓰이고 독립 모듈로 쓰일 일이 없어서다.

## 파일 단위 예외

폴더 기본 담당과 다른 담당자가 배정된 개별 파일. 아래 목록이 위 표보다 우선한다.

| 파일 | 담당 |
| --- | --- |
| `data/mock/generate_dashboard_mock.py` | 최지희 |
| `data/mock/dashboard_mock.json` | 최지희 |
| `data/vessel_spec_client.py` | 김준기, 오동규 |
| `data/ais_stats_client.py` | 김준기, 오동규 |
| `data/marine_weather_client.py` | 김준기, 오동규 |
| `data/tac_status_loader.py` | 김준기, 오동규 |
