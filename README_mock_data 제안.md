# BlueScore Mock 데이터 제작 참고 제안

기존에 **GFW API를 연결한 데모에서 실제로 사용했던 데이터 형태**를 기준으로 정리한 참고안이다.

mock 데이터를 처음부터 새로 정하기보다는,  
**이미 데모에서 받아서 정상적으로 사용해본 선박/조업 이벤트 구조를 기본으로 잡고**,  
아직 구현되지 않은 BlueScore 결과 쪽은 기획서에 맞춰 임시 형식을 정해서 사용하는 방향을 제안한다.

이 문서는 **확정된 스키마가 아니라, mock 데이터 제작 시 참고할 수 있는 출발점**이다.

---

## 1. 실제 데모에서 사용해본 선박 데이터 형태

현재 데모의 `server.js`에서는 GFW에서 받은 선박 데이터를 내부에서 아래처럼 정리해서 사용하고 있다.

```json
{
  "vesselId": "gfw-vessel-id",
  "mmsi": "440000001",
  "imo": null,
  "name": "SAMPLE VESSEL",
  "tonnage": null,
  "length": null,
  "width": null,
  "fishingType": null
}
```

### 참고

- `vesselId`, `mmsi`, `imo`, `name`은 GFW 응답에서 찾아 정리하도록 구현되어 있음
- `tonnage`, `length`, `width`, `fishingType`은 현재 데모에서는 아직 `null`
- 이 값들은 이후 국내 선박제원 데이터와 연결해서 채우는 용도로 용도로 활용할 수 있다.

그래서 **선박 mock 데이터는 이 형태를 기본으로 만들어두면 기존 데모와 연결하기 편리하다.**

예:

```json
{
  "vesselId": "VESSEL_A",
  "mmsi": "440000001",
  "imo": null,
  "name": "BlueSample A",
  "tonnage": 29.0,
  "length": 21.5,
  "width": 5.2,
  "fishingType": "근해어업"
}
```

---

## 2. 실제 데모에서 사용해본 조업 이벤트 형태

GFW 이벤트도 현재 데모에서 한 번 정리해서 아래 형태로 사용하고 있다.

```json
{
  "eventId": "EVENT_A_001",
  "vesselId": "VESSEL_A",
  "start": "2026-07-01T01:00:00Z",
  "end": "2026-07-01T05:00:00Z",
  "latitude": 35.12,
  "longitude": 129.21,
  "durationHours": 4.0,
  "averageSpeedKnots": 4.2,
  "totalDistanceKm": 18.5,
  "mpaRelated": false
}
```

현재 데모에서는 이 정도 정보를 이용해서 이벤트 위치를 지도에 표시하는 흐름까지 연결해본 상태다.

### 필드 의미

- `eventId`: 이벤트 ID
- `vesselId`: 해당 선박 ID
- `start`, `end`: 이벤트 시작/종료 시간
- `latitude`, `longitude`: 이벤트 위치
- `durationHours`: 이벤트 지속시간
- `averageSpeedKnots`: 평균 속도
- `totalDistanceKm`: 이동거리
- `mpaRelated`: 보호구역 관련 여부를 표시하기 위한 값

`mpaRelated`는 현재 코드에서 GFW 원본 응답에 보호구역 관련 정보가 있는지 확인해서 만들어주는 값이다.  
실제 데이터 확인이 더 필요한 부분은 이후 데이터 담당 작업에서 확정하는 것을 권장한다.

---

## 3. 조업 이벤트에는 이런 필드를 추가하면 좋을 것 같음 — 제안

기획서상 이후 기능을 생각하면 mock 단계에서 아래 두 필드도 같이 넣어두는 게 편리하다.

```json
{
  "eventType": "fishing",
  "isGap": false
}
```

그래서 mock에서는 예를 들어:

```json
{
  "eventId": "EVENT_A_001",
  "vesselId": "VESSEL_A",
  "eventType": "fishing",
  "start": "2026-07-01T01:00:00Z",
  "end": "2026-07-01T05:00:00Z",
  "latitude": 35.12,
  "longitude": 129.21,
  "durationHours": 4.0,
  "averageSpeedKnots": 4.2,
  "totalDistanceKm": 18.5,
  "mpaRelated": false,
  "isGap": false
}
```

정도로 만들어두면 A/B축 계산, 지도, GAP 데이터 품질 처리할 때 같이 활용할 수 있다.

**이 두 필드는 기존 데모에서 이미 확정된 구조라기보다, 앞으로 필요한 기능을 고려한 제안이다.**

---

# 여기부터는 아직 실제 결과가 아니라 제안하는 형식

아래 BlueScore, 설명, 시뮬레이션 데이터는  
내가 실제 모델을 돌려서 나온 확정 형식은 아니야.

다만 다른 사람들이 실제 계산이 완성되기 전에도 개발을 시작하려면 결과 형태가 하나 필요하니까,  
**mock에서는 일단 이런 식으로 맞춰보면 어떨까 하는 제안**이야.

개발 과정에서 필요에 따라 수정할 수 있다.

---

## 4. BlueScore 결과 mock 제안

```json
{
  "vesselId": "VESSEL_A",
  "status": "success",
  "blueScore": 72.6,

  "axisA": {
    "score": 81.0,
    "revisitIntervalScore": 84.0,
    "crowdingPressureScore": 78.0
  },

  "axisB": {
    "score": 57.0,
    "expectedFuel": 100.0,
    "estimatedFuel": 108.0,
    "residual": 8.0
  },

  "peerGroup": {
    "count": 42,
    "topPercent": 27
  },

  "improvementRate": 3.2,

  "rate": {
    "grade": "B",
    "discountBp": 12
  }
}
```

이런 구조로 잡아두면 프론트에서는 실제 스코어 계산이 아직 없어도

- 총 BlueScore
- A축/B축
- 유사 선박군 내 위치
- 금리 등급
- 할인 bp

를 먼저 화면에 연결할 수 있다.

---

## 5. SHAP / LLM 설명 결과 mock 제안

```json
{
  "vesselId": "VESSEL_A",

  "summary": "자원 압력 점수는 좋은 편이지만 운항 효율이 상대적으로 낮습니다.",

  "shapFactors": [
    {
      "label": "항해 속도",
      "value": -4.2,
      "direction": "down"
    },
    {
      "label": "조업 반복 간격",
      "value": 3.1,
      "direction": "up"
    }
  ],

  "recommendations": [
    {
      "action": "같은 어장 연속 조업 횟수를 3회에서 2회로 줄이기",
      "expectedScoreChange": 5.1,
      "expectedDiscountBp": 20
    }
  ]
}
```

이것도 아직 확정 형식은 아니고,  
최지희가 SHAP/LLM 부분을 만들기 전에 프론트나 통합 쪽에서 테스트할 수 있도록 잡아본 예시다.

---

## 6. 개선 시뮬레이터 결과 mock 제안

```json
{
  "vesselId": "VESSEL_A",

  "changes": {
    "consecutiveFishingCount": {
      "before": 3,
      "after": 2
    }
  },

  "before": {
    "blueScore": 72.6,
    "topPercent": 27,
    "rateGrade": "B",
    "discountBp": 12
  },

  "after": {
    "blueScore": 77.7,
    "topPercent": 19,
    "rateGrade": "A",
    "discountBp": 20
  }
}
```

시뮬레이터도 실제 계산 로직이 생기면 그 결과로 교체하고,  
처음에는 이런 mock으로 화면 동작만 먼저 확인하는 용도로 사용할 수 있다.

---

## 7. 정상 케이스 말고 실패 케이스도 있으면 좋을 것 같음

기획서에 데이터 부족이나 선박 매칭 실패 시 억지로 점수를 내지 않는 흐름이 있어서,  
mock에서도 이런 경우를 한두 개 만들어두면 프론트 테스트하기 좋다.

### 표본 부족

```json
{
  "vesselId": "VESSEL_D",
  "status": "insufficientSample",
  "reason": "유사 선박군 표본이 부족합니다."
}
```

### 선박 매칭 실패

```json
{
  "vesselId": "VESSEL_E",
  "status": "matchingFailed",
  "reason": "GFW 선박 정보와 국내 선박제원정보를 연결하지 못했습니다."
}
```

상태값 이름 자체는 개발하면서 더 좋은 이름이 있으면 변경해도 된다.

---

## 8. JSON 이름은 기존 데모 기준으로 맞추는 것을 제안

현재 데모가 JavaScript 기반이고 이미 이런 식으로 되어 있어서:

```text
vesselId
averageSpeedKnots
durationHours
totalDistanceKm
```

mock도 일단 `camelCase`로 맞추는 게 연결하기 편리하다.

예를 들어 같은 값을

```text
vessel_id
vesselId
VesselId
```

처럼 사람마다 다르게 사용하지 않도록 통일하는 것이 중요하다.

---

## 9. 정리

기존 GFW API 연동 데모 기준으로,

**선박 데이터와 조업 이벤트는 위 형태로 정리해서 사용했을 때 실제 데모가 정상적으로 동작했다.**

그래서 그 두 부분은 mock 데이터를 만들 때 참고하는 것이 좋고,

BlueScore / A·B축 / SHAP / LLM 설명 / 개선 시뮬레이터 부분은 아직 실제 결과 형식이 확정된 게 아니니까  
**위 예시를 임시안으로 사용하고 개발하면서 팀에서 맞춰가면 된다.**

핵심은 처음부터 완벽한 mock을 만드는 것보다,

> **다섯 명이 같은 키 이름과 같은 구조를 보고 각자 개발을 먼저 시작할 수 있게 만드는 것**

에 있다.
