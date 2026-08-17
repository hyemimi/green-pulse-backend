# 03. API 설명

이 백엔드는 CSV 전체를 그대로 던지는 범용 API가 아니라, 프론트엔드 대시보드에서 바로 쓰기 좋은 형태로 데이터를 가공해서 제공합니다.

원본 CSV와 모델 결과의 역할은 분리되어 있습니다.

```text
fault_type
  실제 정답 라벨
  모델 평가, 실제 fault 구간 비교, 월별 실제 fault count 계산에 사용

predicted_fault
  Python 모델이 생성한 예측 fault
  프론트에서 AI 진단 결과로 보여줄 값
```

## Fault Type 의미

프로젝트 문맥상 fault 값은 아래처럼 사용합니다.

```text
0: Normal
1: F1
2: F2
3: F3
4: F4
```

프론트에서는 `fault_type` 또는 `trueFault`를 "AI 예측"으로 표시하면 안 됩니다.
AI 예측값은 `predictedFault`입니다.


## Swagger 문서

서버 실행 후 아래 주소에서 Swagger UI를 확인할 수 있습니다.

```text
http://localhost:3000/api-docs
```

OpenAPI JSON은 아래 주소에서 받을 수 있습니다.

```text
http://localhost:3000/api-docs-json
```

## GET /health

서버 상태 확인용 API입니다.

응답 예시:

```json
{
  "status": "ok",
  "service": "green-pulse-backend",
  "mode": "precomputed-model-result-api"
}
```

## GET /api/model-runs

DB에 적재된 모델 실행 이력을 반환합니다.

응답 예시:

```json
[
  {
    "id": "fault_run",
    "workspacePath": "/Users/hyemi/green-pulse-backend/fault_run",
    "status": "imported",
    "dataStartAt": "2024-01-01T00:00:00.000Z",
    "dataEndAt": "2025-06-23T23:59:00.000Z",
    "importedAt": "2026-08-16T13:00:00.000Z",
    "notes": "Imported from Python fault diagnosis pipeline outputs."
  }
]
```

프론트 사용처:

- 현재 어떤 모델 결과를 보고 있는지 표시
- 데이터 기준 기간 표시
- 마지막 적재 시점 표시

## GET /api/dashboard/overview

대시보드 첫 화면용 핵심 KPI를 반환합니다.

쿼리 파라미터:

```text
runId?: string
holdMin?: number
```

예시:

```bash
curl "http://localhost:3000/api/dashboard/overview?holdMin=0"
```

응답 구조:

```json
{
  "run": {
    "id": "fault_run",
    "workspacePath": "/path/to/fault_run",
    "status": "imported",
    "dataStartAt": "2024-01-01T00:00:00.000Z",
    "dataEndAt": "2025-06-23T23:59:00.000Z",
    "importedAt": "2026-08-16T13:00:00.000Z",
    "notes": "Imported from Python fault diagnosis pipeline outputs."
  },
  "data": {
    "readingCount": 1555200,
    "faultReadingCount": 55802,
    "normalReadingCount": 1499398,
    "monthCount": 18,
    "reactorCount": 6
  },
  "events": {
    "eventCount": 123,
    "correctEventCount": 45,
    "avgScore": 0.91
  },
  "episodes": {
    "episodeCount": 9,
    "detectedEpisodeCount": 9,
    "within15Count": 7,
    "within30Count": 9,
    "medianDelayMin": 11,
    "wrongBeforeCorrectRate": 0.2222
  },
  "metrics": [
    {
      "group": "arbitration",
      "name": "hold_min",
      "value": 0,
      "text": null
    }
  ]
}
```

주의:

- `readingCount`는 전체 요약 row와 reactor별 row를 같이 집계하면 중복될 수 있습니다.
- 프론트에서 정확한 전체 readings 개수가 필요하면 `reactorId`가 `null`인 monthly summary만 따로 합산하는 API를 추가하는 것이 좋습니다.

## GET /api/dashboard/monthly

월 단위 요약 데이터를 반환합니다.

쿼리 파라미터:

```text
runId?: string
from?: YYYY-MM-DD
to?: YYYY-MM-DD
reactorId?: string
```

예시:

```bash
curl "http://localhost:3000/api/dashboard/monthly?reactorId=A_R1"
```

응답 예시:

```json
[
  {
    "month": "2024-01-01T00:00:00.000Z",
    "reactorId": "A_R1",
    "readingCount": 44640,
    "faultReadingCount": 1200,
    "normalReadingCount": 43440,
    "predictedEventCount": 4,
    "avgReactorTemp": 181.23,
    "avgPressure": 15.7,
    "avgEfficiencyLossPct": 0.42
  }
]
```

프론트 사용처:

- 월별 fault 발생량 차트
- 월별 AI 이벤트 추이
- 월별 평균 온도/압력 차트
- Reactor별 비교

## GET /api/fault-events

모델이 예측한 fault 이벤트 목록을 반환합니다.

쿼리 파라미터:

```text
runId?: string
holdMin?: number
reactorId?: string
from?: ISO datetime 또는 YYYY-MM-DD
to?: ISO datetime 또는 YYYY-MM-DD
limit?: number
```

예시:

```bash
curl "http://localhost:3000/api/fault-events?holdMin=0&limit=10"
```

응답 예시:

```json
[
  {
    "id": 1,
    "eventIndex": 12345,
    "eventTime": "2024-01-09T13:45:00.000Z",
    "reactorId": "A_R2",
    "predictedFault": 1,
    "trueFault": 1,
    "specialist": "thermal_after_hold",
    "score": 0.87,
    "holdMin": 0,
    "episodeId": 17
  }
]
```

필드 설명:

```text
eventIndex
  원본 시계열 CSV 기준 row index

eventTime
  eventIndex에 해당하는 timestamp

predictedFault
  모델 예측 fault

trueFault
  실제 정답 라벨
  비교/평가용으로만 사용

specialist
  어떤 specialist 모델이 만든 이벤트인지 표시

score
  모델 confidence 또는 점수

holdMin
  thermal arbitration hold 설정값

episodeId
  fault episode 식별자
```

프론트 사용처:

- AI 진단 이벤트 타임라인
- Fault 이벤트 테이블
- Reactor별 이벤트 필터
- 예측값과 실제값 비교 UI

## GET /api/episodes

fault episode 단위의 탐지 성능을 반환합니다.

쿼리 파라미터:

```text
runId?: string
holdMin?: number
```

예시:

```bash
curl "http://localhost:3000/api/episodes?holdMin=0"
```

응답 예시:

```json
[
  {
    "episodeId": 17,
    "fault": 1,
    "reactorId": "A_R2",
    "correctDelayMin": 2,
    "wrongDelayMin": null,
    "wrongBeforeCorrect": false
  }
]
```

필드 설명:

```text
fault
  실제 fault 라벨

correctDelayMin
  fault onset 이후 모델이 정답 fault를 맞히기까지 걸린 시간

wrongDelayMin
  정답보다 먼저 잘못된 fault를 낸 경우의 시간

wrongBeforeCorrect
  정답 예측 전에 오진이 있었는지 여부
```

프론트 사용처:

- 모델 성능 요약
- 에피소드별 탐지 지연 시간 표
- 15분/30분 이내 탐지율 시각화

## GET /api/reactors/:reactorId/readings

특정 reactor의 원본 센서 시계열 일부를 반환합니다.

경로 파라미터:

```text
reactorId: string
```

쿼리 파라미터:

```text
from?: ISO datetime 또는 YYYY-MM-DD
to?: ISO datetime 또는 YYYY-MM-DD
limit?: number
```

예시:

```bash
curl "http://localhost:3000/api/reactors/A_R1/readings?limit=5"
```

응답 예시:

```json
[
  {
    "timestamp": "2024-01-01T00:00:00.000Z",
    "reactorId": "A_R1",
    "reactorTemp": 181.13,
    "reactorPressure": 15.79,
    "feedFlowRate": 101.1,
    "coolantFlowRate": 79.15,
    "agitatorSpeedRpm": 305.78,
    "vibrationRms": 1.47,
    "motorCurrent": 45.88,
    "powerConsumptionKw": 41.29,
    "faultType": 0,
    "efficiencyLossPct": 0
  }
]
```

프론트 사용처:

- Reactor별 센서 라인 차트
- 실제 fault 구간 표시
- AI 이벤트와 센서 변화 비교

## 현재 API의 한계

현재 API는 프론트 대시보드에 필요한 핵심 데이터 위주입니다.
CSV의 모든 컬럼을 자유롭게 선택해서 조회하는 범용 API는 아닙니다.

추가하면 좋은 API:

```text
GET /api/readings?reactorId=A_R1&from=2024-01-01&to=2024-01-31&faultType=1&limit=1000
```

이 API를 만들면 원본 CSV 기반 상세 테이블이나 더 복잡한 분석 화면을 만들기 쉬워집니다.
