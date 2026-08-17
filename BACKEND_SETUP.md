# Green-Pulse Backend Setup

이 백엔드는 Python 모델을 실시간으로 실행하지 않습니다.
모델은 먼저 배치 스크립트로 돌리고, 생성된 CSV 결과를 PostgreSQL에 적재한 뒤 Nest.js API가 프론트에 제공합니다.

## 1. Python 모델 실행

프로젝트 루트에서 아래 명령을 실행합니다.

```bash
python fault_diagnosis_pipeline.py --workspace ./fault_run
```

Python 패키지가 부족하면 먼저 필요한 패키지를 설치해야 합니다.
이 파일의 모델은 `pandas`, `numpy`, `scikit-learn`, `xgboost`, `numba`, `matplotlib` 등을 사용합니다.

검증만 하고 싶을 때는 아래처럼 실행합니다.

```bash
python fault_diagnosis_pipeline.py --workspace ./fault_run --validate-only
```

모델 실행이 끝나면 아래 파일들이 있어야 합니다.

```text
fault_run/integrated_arbitration_v2/final_events_all_holds.csv
fault_run/integrated_arbitration_v2/episode_results_hold0.csv
fault_run/integrated_arbitration_v2/arbitration_summary.csv
fault_run/integrated_specialists_v1_outputs/integrated_overall_summary.csv
```

## 2. PostgreSQL 실행

Docker를 쓰는 경우:

```bash
docker compose up -d
```

직접 PostgreSQL을 쓰는 경우에는 `.env.example`을 참고해 `DATABASE_URL`을 맞춥니다.

## 3. DB 스키마 생성

```bash
DATABASE_URL=postgres://green_pulse:green_pulse@localhost:5432/green_pulse npm run db:migrate
```

## 4. 모델 결과 적재

```bash
DATABASE_URL=postgres://green_pulse:green_pulse@localhost:5432/green_pulse MODEL_WORKSPACE=./fault_run npm run import:results
```

적재 스크립트는 아래 작업을 수행합니다.

- 원본 `chemical_process_timeseries.csv`를 `reactor_readings`에 저장합니다.
- 모델 이벤트 결과를 `fault_events`에 저장합니다.
- 에피소드별 탐지 결과를 `episode_results`에 저장합니다.
- 월 단위 프론트 조회용 데이터를 `monthly_summaries`에 생성합니다.
- 모델 실행 단위는 `model_runs`에 저장합니다.

## 5. Nest.js API 실행

```bash
DATABASE_URL=postgres://green_pulse:green_pulse@localhost:5432/green_pulse npm run start:dev
```

기본 주소:

```text
http://localhost:3000
```

## 주요 API

```text
GET /health
GET /api/model-runs
GET /api/dashboard/overview
GET /api/dashboard/monthly
GET /api/fault-events
GET /api/episodes
GET /api/reactors/:reactorId/readings
```

예시:

```bash
curl "http://localhost:3000/api/dashboard/overview"
curl "http://localhost:3000/api/dashboard/monthly?reactorId=A_R1"
curl "http://localhost:3000/api/fault-events?holdMin=0&limit=50"
curl "http://localhost:3000/api/reactors/A_R1/readings?limit=120"
```

## 포트폴리오 설명 문장

이 프로젝트는 제한된 기간의 공정 시계열 데이터를 대상으로 Python 기반 fault diagnosis 모델을 배치 실행하고, 생성된 예측 이벤트와 월별 요약 지표를 PostgreSQL에 적재한 뒤 Nest.js API로 제공하는 구조입니다. 실시간 추론 서버 대신 사전 계산된 모델 결과를 데이터 제품화하여 프론트엔드 대시보드가 빠르게 조회할 수 있도록 설계했습니다.
