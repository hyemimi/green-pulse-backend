# ESG 절감량 API 개발 가이드

이 브랜치는 전력 절감 계산식이 확정되기 전에 준비할 수 있는 DB, CSV 적재, 월별 집계, CO2 환산 API를 구현합니다.

중요: 예제 CSV의 숫자는 형식 설명용이며 실제 DB에 적재하지 않습니다. 실제 결과는 Python 계산식 확정 후 생성합니다.

## 1. 전체 흐름

```text
chemical_process_timeseries_physics.csv
  -> scripts/calculate_esg_energy.py
  -> fault_run/esg/energy_savings.csv
  -> npm run import:results
  -> PostgreSQL esg_energy_savings
  -> GET /api/esg/summary, GET /api/esg/monthly
```

Python은 행별 `energy_saved_kwh`를 계산합니다. NestJS는 그 값을 다시 계산하지 않고 기간·월·반응기별로 합산한 뒤 CO2와 생활지표로 환산합니다.

## 2. 팀에서 먼저 확정할 내용

1. F1/F2/F3의 STY 손실률 계산식과 정상 기준선
2. F4의 정상 모터 전류 및 초과 전력 계산식
3. 탐지 이후 어느 구간까지를 절감 가능 구간으로 볼지
4. 결측치를 제외할지 보간할지
5. CO2 계수, 전기요금 단가, 연간 목표량 및 각 값의 버전

## 3. Python 계산식 넣기

`scripts/calculate_esg_energy.py`의 `calculate_energy_saved_kwh()`만 수정합니다.

1분 간격 데이터에서 전력 kW를 전력량 kWh로 바꿀 때는 최종 확정된 낭비 전력 kW에 `1 / 60`을 곱해야 합니다.

함수는 입력 행과 동일한 인덱스를 갖는 `pd.Series`를 반환해야 합니다. 값은 0 이상이어야 하며, 계산 불가 행을 임의로 0으로 만들면 안 됩니다.

```bash
python3 scripts/calculate_esg_energy.py \
  --output fault_run/esg/energy_savings.csv \
  --version sty-v1
```

스크립트는 기본적으로 `chemical_process_timeseries_physics.csv`를 사용합니다. 현재 작업공간처럼 백엔드 저장소와 데이터 저장소가 나란히 있으면 첨부된 파일을 자동으로 찾습니다.

다른 위치에서 실행할 때는 환경변수나 `--input`으로 경로를 지정합니다.

```powershell
$env:PHYSICS_DATASET_PATH="C:\data\chemical_process_timeseries_physics.csv"
python scripts/calculate_esg_energy.py --version sty-v1
```

`space_time_yield`는 새 CSV에 이미 계산되어 있으므로 Python ESG 계산에서는 이 컬럼을 입력값으로 사용합니다.

현재는 계산식 미확정 상태이므로 실행하면 `NotImplementedError`가 발생합니다. 이것은 미완성 계산 결과가 DB에 들어가는 것을 막기 위한 장치입니다.

## 4. 결과 CSV 규격

필수 컬럼:

```text
timestamp
reactor_id
fault_type
energy_saved_kwh
calculation_method
calculation_version
```

추적성과 검증을 위한 권장 컬럼:

```text
episode_id
baseline_sty
actual_sty
baseline_power_kw
actual_power_kw
```

형식 예시는 `docs/examples/energy_savings.example.csv`에서 확인할 수 있습니다.

## 5. DB 생성 및 결과 적재

PowerShell에서는 먼저 환경변수를 설정합니다.

```powershell
$env:DATABASE_URL="postgres://localhost:5432/green_pulse"
$env:MODEL_WORKSPACE="./fault_run"
```

macOS/Linux에서는 다음과 같이 설정합니다.

```bash
export DATABASE_URL="postgres://localhost:5432/green_pulse"
export MODEL_WORKSPACE="./fault_run"
```

```bash
npm run db:migrate
```

위 명령은 기존 테이블과 `esg_energy_savings` 테이블을 함께 생성합니다.

Python 결과가 없는 상태에서도 기존 모델 결과는 정상적으로 적재됩니다. ESG CSV가 없으면 경고만 출력하고 ESG 적재를 건너뜁니다.

```bash
npm run import:results
```

확인:

```sql
SELECT COUNT(*) FROM esg_energy_savings;
SELECT SUM(energy_saved_kwh) FROM esg_energy_savings;
SELECT DATE_TRUNC('month', timestamp), SUM(energy_saved_kwh)
FROM esg_energy_savings
GROUP BY 1
ORDER BY 1;
```

## 6. 환경변수 설정

`.env.example`을 복사하여 `.env`를 만들고 팀에서 확정한 값으로 변경합니다.

```env
CO2_FACTOR_KG_PER_KWH=0.4541
PAPER_CUP_CO2_KG=0.0452
CAR_CO2_KG_PER_KM=0.14
PINE_TREE_CO2_KG_PER_YEAR=125
TISSUE_ROLL_CO2_KG=0.288
ELECTRICITY_PRICE_KRW_PER_KWH=0
ANNUAL_ENERGY_TARGET_KWH=0
ESG_FACTOR_VERSION=project-draft-v1
```

`ELECTRICITY_PRICE_KRW_PER_KWH`와 `ANNUAL_ENERGY_TARGET_KWH`가 0이면 비용은 0, 목표 달성률은 `null`로 반환됩니다.

## 7. API 실행 및 확인

```bash
npm run start:dev
```

Swagger:

```text
http://localhost:3000/api-docs
```

전체 ESG 요약:

```bash
curl "http://localhost:3000/api/esg/summary?from=2024-01-01&to=2024-03-31"
```

월별 추이:

```bash
curl "http://localhost:3000/api/esg/monthly?from=2024-01-01&to=2024-03-31"
```

특정 반응기:

```bash
curl "http://localhost:3000/api/esg/monthly?reactorId=A_R1"
```

환산계수:

```bash
curl "http://localhost:3000/api/esg/conversion-factors"
```

## 8. 계산식 확정 후 검증

1. Python 결과에 음수·결측치가 없는지 확인합니다.
2. 월별 합계의 합이 전체 합계와 같은지 확인합니다.
3. 최종 물리모델과 같은 버전의 계산식이라면 3개월 합계를 해당 모델 결과와 대조합니다.
4. API의 `energySavedKwh`가 DB의 `SUM(energy_saved_kwh)`와 같은지 확인합니다.
5. `co2ReducedKg = energySavedKwh * CO2_FACTOR_KG_PER_KWH`인지 확인합니다.
6. Swagger에서 기간 및 반응기 필터를 각각 테스트합니다.

API 응답은 `measurementMode: ESTIMATED`를 표시합니다. 실제 정비·조치 이력이 추가되기 전까지 실제 확정 절감량으로 표현하지 않습니다.
