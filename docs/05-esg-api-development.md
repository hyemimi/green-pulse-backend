# ESG 절감량 백엔드 계산 가이드

## 사용하는 CSV 구분

- `chemical_process_timeseries_final.csv`: 머신러닝 모델 학습용
- `economic_power_calculation_5cols.csv`: ESG 전력 절감량 계산용

백엔드는 전력 계산 CSV의 다음 5개 컬럼만 `economic_power_readings` 테이블에 적재하여 사용합니다.

```text
timestamp
operating_regime
reactor_id
fault_type
wasted_power_kw
```

대용량 CSV를 Render 서버가 API 요청마다 직접 읽지 않습니다. CSV를 Neon DB에 한 번 적재하고, API는 필요한 시간 구간만 DB에서 조회합니다.

## Python 코드와 동일한 계산식

```text
actual_loss_until_detection_kwh
  = 고장 시작 시각 이상, 탐지 시각 미만의 wasted_power_kw 합계 / 60

saved_kwh
  = MAX(운전 조건·고장 종류별 미조치 평균 총손실량
        - actual_loss_until_detection_kwh, 0)

saving_rate_pct
  = saved_kwh / 미조치 평균 총손실량 × 100
```

데이터 간격은 1분이므로 `kW × 1/60시간 = kWh`가 되어 합계를 60으로 나눕니다. 탐지 시각의 행은 누적 손실 구간에서 제외합니다.

`wasted_power_kw`는 CSV 값을 그대로 사용합니다. `power_consumption_kw`나 `efficiency_loss_pct`로 다시 계산하지 않습니다.

## 운전 조건·고장 종류별 미조치 평균 총손실량

단위는 `kWh / episode`입니다.

| 운전 조건 | F1 | F2 | F3 | F4 |
|---|---:|---:|---:|---:|
| A | 3.520724 | 66.480152 | 0.684389 | 36.743387 |
| B | 3.910796 | 38.773997 | 2.894215 | 24.382986 |

## DB 테이블 생성 및 CSV 적재

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행합니다.

```powershell
npm.cmd run db:migrate
$env:ECONOMIC_POWER_CSV='C:\실제경로\economic_power_calculation_5cols.csv'
npm.cmd run import:economic-power
```

완료되면 다음과 같이 출력됩니다.

```text
[IMPORT] economic_power_readings complete rows=777600
```

같은 CSV를 다시 적재해도 `reactor_id + timestamp`가 같은 행은 업데이트되므로 중복되지 않습니다.

## 개별 탐지 계산 API

```http
GET /api/esg/power-saving
```

필수값은 `reactorId`, `predictedFault`, `onsetTimestamp`입니다. `detectTimestamp` 또는 `detectMinute` 중 하나를 함께 전달합니다.

```bash
curl "http://localhost:3000/api/esg/power-saving?reactorId=B_R3&predictedFault=F2&onsetTimestamp=2024-03-29T04:04:00Z&detectMinute=15"
```

전력 계산 CSV 기준 예시 결과:

```json
{
  "reactorId": "B_R3",
  "operatingRegime": "B",
  "predictedFault": 2,
  "actualFaultAtDetection": 2,
  "faultMatch": true,
  "detectMinute": 15,
  "wastedPowerKwAtDetection": 0.949614,
  "integratedMinutes": 15,
  "unmitigatedLossKwh": 38.773997,
  "actualLossUntilDetectionKwh": 0.082754,
  "savedKwh": 38.691243,
  "savingRatePct": 99.79
}
```

## 전체 및 월별 API

```http
GET /api/esg/summary
GET /api/esg/monthly
```

두 API는 `episode_results`의 탐지 지연 시간과 `fault_events`의 최초 정답 탐지 시각으로 각 에피소드의 시작 시각을 계산합니다. 이후 `economic_power_readings`에서 해당 구간의 `wasted_power_kw`를 합산합니다.

선택 필터는 `runId`, `from`, `to`, `reactorId`, `holdMin`입니다.

## 공정 모니터링 반응기별 전력 손실 API

```http
GET /api/esg/reactor-losses?holdMin=0
```

각 반응기의 고장 에피소드를 합산하여 다음 값을 반환합니다.

```text
unmitigatedLossKwh: 조치하지 않고 방치했을 때의 예상 총 전력 손실
actualLossUntilDetectionKwh: 고장 시작부터 AI 탐지 전까지 실제 발생한 손실
avoidableLossKwh: AI 조기 탐지로 예방 가능한 전력 손실
savingRatePct: 방치 시 손실 중 예방 가능한 비율
```

실시간 데모에서는 `playbackMinute`을 0부터 1씩 증가시켜 호출합니다.

```http
GET /api/esg/reactor-losses?holdMin=0&playbackMinute=5
```

각 에피소드의 계산 시각은 `고장 시작 시각 + playbackMinute`이며, 실제 ML 탐지 시각을 넘지 않습니다. 따라서 예방 가능 전력량은 매 공정 1분마다 해당 구간의 `wasted_power_kw / 60`만큼 감소하고, 탐지가 완료된 뒤에는 최종 `saved_kwh`에서 멈춥니다.

## ESG 환산계수 API

```http
GET /api/esg/conversion-factors
```

전력 절감량을 CO2, 종이컵, 자동차 주행거리, 소나무, 휴지 등으로 환산하는 계수와 현재 전력 계산 기준을 반환합니다.

```env
CO2_FACTOR_KG_PER_KWH=0.5304
PAPER_CUP_CO2_KG=0.0452
CAR_CO2_KG_PER_KM=0.14
PINE_TREE_CO2_KG_PER_YEAR=125
TISSUE_ROLL_CO2_KG=0.288
ELECTRICITY_PRICE_KRW_PER_KWH=150
ANNUAL_ENERGY_TARGET_KWH=0
ESG_FACTOR_VERSION=economic-power-csv-v2
```

## 실행 확인

```powershell
npm.cmd run build
npm.cmd run start:dev
```

Swagger는 `http://localhost:3000/api-docs`에서 확인합니다.
