# 01. 백엔드 Set Up 방법

이 프로젝트의 백엔드는 Python 모델을 실시간으로 실행하지 않습니다.
Python 모델을 먼저 배치로 실행하고, 그 결과 CSV를 PostgreSQL에 적재한 뒤 Nest.js API가 프론트엔드에 제공합니다.

## 전체 구조

```text
chemical_process_timeseries.csv
  -> Python 모델 실행
  -> fault_run/ 결과 CSV 생성
  -> PostgreSQL 적재
  -> Nest.js API 조회
  -> Frontend Dashboard
```

## 1. 필요한 프로그램

- Node.js
- npm
- Python 3
- PostgreSQL

Docker는 필수는 아닙니다.
로컬에 PostgreSQL을 직접 설치해서 쓰고 있다면 Docker 없이 진행해도 됩니다.

## 2. 의존성 설치

```bash
npm install
```

Python 모델 실행에 필요한 패키지:

```bash
python3 -m pip install pandas numpy scikit-learn xgboost numba matplotlib
```

현재 Mac 기본 Python이 3.9인 경우 `python` 명령이 없을 수 있습니다.
그럴 때는 `python3`를 사용합니다.

```bash
python3 --version
```

## 3. PostgreSQL DB 생성

로컬 PostgreSQL을 사용하는 경우:

```bash
createdb green_pulse
```

이미 존재한다고 나오면 정상입니다.

```text
database "green_pulse" already exists
```

## 4. 환경변수 설정

이 프로젝트에서 가장 중요한 환경변수는 `DATABASE_URL`입니다.
백엔드와 적재 스크립트가 어떤 PostgreSQL DB에 접속할지 알려주는 값입니다.

로컬 PostgreSQL 기준:

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse
```

`.env` 파일을 사용할 수 있습니다.

```env
DATABASE_URL=postgres://localhost:5432/green_pulse
PORT=3000
CORS_ORIGIN=http://localhost:5173,https://dev-green-pulse-frontend.onrender.com
MODEL_WORKSPACE=./fault_run
```

단, zsh에서 단순히 아래처럼 실행하면 npm 자식 프로세스에 환경변수가 전달되지 않을 수 있습니다.

```bash
source .env
```

그래서 `.env`를 사용할 때는 아래처럼 실행하는 것이 안전합니다.

```bash
set -a
source .env
set +a
```

또는 명령 앞에 직접 붙여도 됩니다.

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse npm run db:migrate
```

## 5. DB 테이블 생성

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse npm run db:migrate
```

성공하면 `CREATE TABLE`, `CREATE INDEX` 메시지가 출력됩니다.

테이블 확인:

```bash
psql postgres://localhost:5432/green_pulse
```

```sql
\dt
```

생성되는 주요 테이블:

```text
model_runs
reactor_readings
fault_events
episode_results
run_metrics
monthly_summaries
```

## 6. Python 모델 실행

모델 결과 폴더를 생성합니다.

```bash
python3 fault_diagnosis_pipeline.py --workspace ./fault_run
```

검증만 하고 싶으면:

```bash
python3 fault_diagnosis_pipeline.py --workspace ./fault_run --validate-only
```

모델 실행이 끝나면 아래 파일들이 생성되어야 합니다.

```text
fault_run/integrated_arbitration_v2/final_events_all_holds.csv
fault_run/integrated_arbitration_v2/episode_results_hold0.csv
fault_run/integrated_arbitration_v2/arbitration_summary.csv
fault_run/integrated_specialists_v1_outputs/integrated_overall_summary.csv
```

## 7. 모델 결과 DB 적재

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse MODEL_WORKSPACE=./fault_run npm run import:results
```

이 작업은 서버 또는 DB 기준으로 보통 한 번만 하면 됩니다.

다시 실행해야 하는 경우:

- DB를 새로 만든 경우
- 서버를 새로 배포한 경우
- 원본 CSV가 바뀐 경우
- Python 모델 결과를 새로 생성한 경우
- `fault_run` 폴더를 다시 만들었거나 다른 결과 폴더를 쓰는 경우

반대로 단순히 Nest.js 서버를 껐다 켜는 경우에는 다시 적재할 필요가 없습니다.

## 8. 적재 확인

```bash
psql postgres://localhost:5432/green_pulse
```

```sql
SELECT COUNT(*) FROM model_runs;
SELECT COUNT(*) FROM reactor_readings;
SELECT COUNT(*) FROM fault_events;
SELECT COUNT(*) FROM episode_results;
SELECT COUNT(*) FROM monthly_summaries;
SELECT COUNT(*) FROM run_metrics;
```

`model_runs`가 0이면 모델 결과가 아직 DB에 적재되지 않은 상태입니다.

## Docker는 필요한가?

현재 로컬 PostgreSQL을 직접 사용한다면 Docker는 필요 없습니다.

`docker-compose.yml`은 Docker로 PostgreSQL을 띄우고 싶은 경우를 위한 선택지입니다.
Docker가 설치되어 있지 않아도 로컬 PostgreSQL만 정상 실행 중이면 백엔드는 문제없이 동작합니다.
