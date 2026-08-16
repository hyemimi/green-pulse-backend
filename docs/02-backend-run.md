# 02. 백엔드 실행 방법

이 문서는 DB 세팅과 모델 결과 적재가 끝난 뒤 Nest.js 백엔드를 실행하고 테스트하는 방법을 설명합니다.

## 1. 실행 전 확인

DB 테이블이 있어야 합니다.

```bash
psql postgres://localhost:5432/green_pulse -c "\dt"
```

모델 결과가 적재되어 있어야 합니다.

```bash
psql postgres://localhost:5432/green_pulse -c "SELECT COUNT(*) FROM model_runs;"
```

`model_runs`가 1 이상이면 적재된 모델 실행 결과가 있는 상태입니다.

## 2. 개발 서버 실행

환경변수를 명령 앞에 직접 붙이는 방식:

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse npm run start:dev
```

`.env`를 사용하는 방식:

```bash
set -a
source .env
set +a
npm run start:dev
```

서버는 기본적으로 아래 주소에서 실행됩니다.

```text
http://localhost:3000
```

## 3. Health Check

새 터미널에서 실행합니다.

```bash
curl http://localhost:3000/health
```

정상 응답 예시:

```json
{
  "status": "ok",
  "service": "green-pulse-backend",
  "mode": "precomputed-model-result-api"
}
```

## 4. Swagger API 문서 확인

Swagger UI는 아래 주소에서 확인할 수 있습니다.

```text
http://localhost:3000/api-docs
```

OpenAPI JSON이 필요하면 아래 주소를 사용합니다.

```text
http://localhost:3000/api-docs-json
```

Swagger 화면에서는 각 API의 쿼리 파라미터, 응답 예시, 프론트 연동용 필드명을 확인할 수 있습니다.

## 5. 주요 API 테스트

```bash
curl http://localhost:3000/api/model-runs
```

```bash
curl http://localhost:3000/api/dashboard/overview
```

```bash
curl "http://localhost:3000/api/dashboard/monthly?reactorId=A_R1"
```

```bash
curl "http://localhost:3000/api/fault-events?holdMin=0&limit=10"
```

```bash
curl "http://localhost:3000/api/episodes?holdMin=0"
```

```bash
curl "http://localhost:3000/api/reactors/A_R1/readings?limit=5"
```

## 6. 자주 나는 문제

### `database "hyemi" does not exist`

`DATABASE_URL`이 npm 프로세스에 전달되지 않은 상태입니다.

아래처럼 직접 붙여 실행합니다.

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse npm run start:dev
```

또는 `.env`를 export 방식으로 적용합니다.

```bash
set -a
source .env
set +a
```

### `/api/dashboard/overview`가 500을 반환함

대부분 모델 결과가 아직 DB에 적재되지 않은 경우입니다.

확인:

```bash
psql postgres://localhost:5432/green_pulse -c "SELECT * FROM model_runs;"
```

비어 있으면 적재를 실행합니다.

```bash
DATABASE_URL=postgres://localhost:5432/green_pulse MODEL_WORKSPACE=./fault_run npm run import:results
```

### `No module named 'numba'`

Python 모델 실행에 필요한 패키지가 빠진 상태입니다.

```bash
python3 -m pip install pandas numpy scikit-learn xgboost numba matplotlib
```

### `zsh: command not found: python`

Mac에서는 보통 `python` 대신 `python3`를 사용합니다.

```bash
python3 fault_diagnosis_pipeline.py --workspace ./fault_run
```
