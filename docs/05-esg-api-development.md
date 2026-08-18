# ESG 절감량 백엔드 계산 가이드

ESG 절감량은 별도 Python CSV를 만들지 않고 NestJS가 Neon DB의 원본 데이터와 ML 탐지 결과를 조회하여 계산합니다.

## 계산 흐름

```text
reactor_readings 원본 전력·효율손실 값
  + fault_events ML 탐지 시각
  + episode_results 탐지 지연시간
  -> 결함 시작부터 탐지 직전까지 실제 손실 적분
  -> 미조치 평균 총손실에서 차감
  -> 예상 절감 전력량
  -> CO2 및 생활지표 환산
```

## 사용한 계산식

전달받은 Python 식에는 `wasted_power_kw`가 필요하지만 현재 DB에는 해당 컬럼이 없습니다. 현재 DB의 원본 컬럼으로 다음과 같이 계산합니다.

```text
wasted_power_kw
  = power_consumption_kw × efficiency_loss_pct ÷ 100

actual_loss_until_detection_kwh
  = 결함 시작 이상, 탐지 시각 미만의 wasted_power_kw 합계 ÷ 60

saved_kwh
  = MAX(레짐·결함별 미조치 평균 총손실 - actual_loss_until_detection_kwh, 0)

saving_rate_pct
  = saved_kwh ÷ 미조치 평균 총손실 × 100
```

데이터는 1분 간격이므로 kW 합계를 kWh로 바꾸기 위해 60으로 나눕니다. 탐지 시각 행은 누적 손실 구간에서 제외합니다.

## 레짐·결함별 미조치 평균 총손실

단위는 `kWh / episode`입니다.

| 레짐 | F1 | F2 | F3 | F4 |
|---|---:|---:|---:|---:|
| A | 3.520724 | 66.480152 | 0.684389 | 36.743387 |
| B | 3.910796 | 38.773997 | 2.894215 | 24.382986 |

## 개별 탐지 계산 API

```http
GET /api/esg/power-saving
```

필수값:

```text
reactorId
predictedFault
onsetTimestamp
```

`detectTimestamp` 또는 `detectMinute` 중 하나를 함께 전달합니다.

예시:

```bash
curl "http://localhost:3000/api/esg/power-saving?reactorId=B_R3&predictedFault=F2&onsetTimestamp=2024-03-29T04:04:00Z&detectMinute=15"
```

Neon 원본 데이터 기준 예시 결과:

```json
{
  "reactorId": "B_R3",
  "operatingRegime": "B",
  "predictedFault": 2,
  "actualFaultAtDetection": 2,
  "faultMatch": true,
  "detectMinute": 15,
  "integratedMinutes": 15,
  "unmitigatedLossKwh": 38.773997,
  "actualLossUntilDetectionKwh": 0.504404,
  "savedKwh": 38.269593,
  "savingRatePct": 98.7
}
```

## 전체 및 월별 API

```http
GET /api/esg/summary
GET /api/esg/monthly
```

두 API는 `episode_results`의 탐지 지연시간과 `fault_events`의 최초 정답 탐지 시각을 이용하여 각 에피소드의 시작 시각을 계산합니다. 각 에피소드별 `saved_kwh`를 합산한 뒤 CO2와 생활지표로 환산합니다.

선택 가능한 필터:

```text
runId
from
to
reactorId
holdMin
```

예시:

```bash
curl "http://localhost:3000/api/esg/summary?holdMin=0"
curl "http://localhost:3000/api/esg/monthly?from=2024-01-01&to=2024-03-31&holdMin=0"
curl "http://localhost:3000/api/esg/monthly?reactorId=A_R1&holdMin=0"
```

## 환산계수 API

```http
GET /api/esg/conversion-factors
```

이 API는 CO2·종이컵·자동차·소나무·휴지 환산계수뿐 아니라 백엔드에서 적용 중인 전력 계산식과 레짐·결함별 미조치 총손실 값도 반환합니다.

환경변수:

```env
CO2_FACTOR_KG_PER_KWH=0.4541
PAPER_CUP_CO2_KG=0.0452
CAR_CO2_KG_PER_KM=0.14
PINE_TREE_CO2_KG_PER_YEAR=125
TISSUE_ROLL_CO2_KG=0.288
ELECTRICITY_PRICE_KRW_PER_KWH=0
ANNUAL_ENERGY_TARGET_KWH=0
ESG_FACTOR_VERSION=backend-db-v1
```

## 실행 및 확인

로컬 `.env`에 개발용 Neon `DATABASE_URL`을 설정한 뒤 실행합니다. DB URL은 Git에 올리지 않습니다.

```powershell
npm.cmd run build
npm.cmd run start:dev
```

Swagger:

```text
http://localhost:3000/api-docs
```

별도 ESG 테이블 생성과 Python 결과 CSV 적재는 필요하지 않습니다.
