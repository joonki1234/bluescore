# 담당: 김태윤

`sample_vessels.json`, `sample_events.json`은 실제로 수집한 GFW 데이터
+ 국내 선박제원 매칭 결과(`data/raw/gfw_vessels_enriched.jsonl.gz`,
실제 라이브 API 호출 결과)에서 그대로 뽑은 샘플이다 — 조작하거나
지어낸 값이 아니라 실제 선박 3척(`confirmed_fishing`으로 매칭 확정된
것들)과 그 선박들의 실제 이벤트 4건(fishing/port_visit/encounter/
loitering 각 1건)이다.

`README_mock_data 제안.md`(1~2번)에서 제안한 필드 구조와 정확히
일치하도록 맞췄고, 3번에서 제안했던 `eventType`/`isGap` 필드도
`data/gfw_client.py`의 `_normalize_event()`에 실제로 반영해서(2026-08-14)
포함했다.

**포함 안 된 것:** GAP 타입 이벤트 — 뽑은 3척의 최근 기간 안에 GAP
이벤트가 없어서 샘플에 못 넣었다. 필요하면 추가로 뽑을 수 있다.
BlueScore/A·B축/SHAP·LLM 설명/개선 시뮬레이터 mock(제안서 4~6번)은
아직 실제 계산 로직이 없는 영역(score/, explain/ 담당)이라 이 폴더엔
포함하지 않는다 — 필요하면 각 담당자가 제안서를 참고해서 직접 만드는
게 맞다.
