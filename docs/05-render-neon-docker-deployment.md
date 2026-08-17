# 05. Render + Neon + Docker 배포 가이드

이 문서는 Green-Pulse 백엔드를 Render에 Docker 기반 Web Service로 배포하고, PostgreSQL은 Neon을 사용하는 방법을 설명합니다.

## 1. 권장 인프라 구조

```text
Frontend
  -> Render Web Service: Nest.js API Docker container
  -> Neon PostgreSQL: model results + dashboard data
```

중요한 점은 Render 컨테이너가 Python 모델을 실행하지 않는다는 것입니다.
Render는 API 서버만 담당하고, 모델 실행 결과는 미리 Neon DB에 적재합니다.

```text
Local machine
  -> python3 fault_diagnosis_pipeline.py --workspace ./fault_run
  -> DATABASE_URL=<Neon URL> MODEL_WORKSPACE=./fault_run npm run import:results

Render
  -> Docker image build
  -> node dist/main.js
  -> Neon DB 조회
```

## 2. 왜 모델 적재를 Render에서 하지 않는가

원본 CSV가 크고 `fault_run/` 결과물도 배포 이미지에 넣기에는 부적합합니다.
또한 모델 적재는 매 요청마다 필요한 작업이 아니라 DB 기준으로 한 번 실행하면 되는 작업입니다.

따라서 포트폴리오/운영 구조는 아래처럼 분리하는 것이 좋습니다.

| 작업 | 실행 위치 | 실행 빈도 |
|---|---|---:|
| Python 모델 실행 | 로컬 또는 별도 배치 환경 | 데이터/모델 변경 시 |
| DB migration | 로컬 또는 Render one-off/manual shell | 배포 초기 또는 스키마 변경 시 |
| 모델 결과 import | 로컬에서 Neon으로 직접 적재 | 모델 결과 변경 시 |
| Nest.js API 서버 | Render Docker Web Service | 항상 실행 |

## 3. Neon DB 생성

1. Neon에서 새 Project를 생성합니다.
2. 기본 DB 또는 `green_pulse` DB를 준비합니다.
3. Connect 버튼을 눌러 connection string을 복사합니다.
4. connection string에 SSL 옵션이 포함되어 있는지 확인합니다.

예시:

```text
postgresql://USER:PASSWORD@ep-xxxx-pooler.region.aws.neon.tech/green_pulse?sslmode=require&channel_binding=require
```

Neon은 TLS/SSL 연결이 필요합니다. Dashboard에서 복사한 URL을 그대로 쓰는 것을 추천합니다.

## 4. Neon에 테이블 생성

로컬 터미널에서 실행합니다.

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require&channel_binding=require" npm run db:migrate:node
```

기존 `npm run db:migrate`는 `psql` CLI를 사용합니다.
Docker/Render 환경에서는 `psql`이 없을 수 있으므로 Neon 배포용으로는 Node 기반 migration 명령을 추천합니다.

```bash
npm run db:migrate:node
```

## 5. 모델 결과를 Neon에 적재

먼저 로컬에서 모델을 실행합니다.

```bash
python3 fault_diagnosis_pipeline.py --workspace ./fault_run
```

그 다음 Neon DB로 결과를 적재합니다.

```bash
DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require&channel_binding=require" MODEL_WORKSPACE=./fault_run npm run import:results
```

적재 확인:

```bash
psql "postgresql://USER:PASSWORD@HOST/DB?sslmode=require&channel_binding=require" -c "SELECT COUNT(*) FROM model_runs;"
psql "postgresql://USER:PASSWORD@HOST/DB?sslmode=require&channel_binding=require" -c "SELECT COUNT(*) FROM fault_events;"
```

## 6. Docker 로컬 테스트

이미지 빌드:

```bash
docker build -t green-pulse-backend .
```

컨테이너 실행:

```bash
docker run --rm -p 3000:10000   -e PORT=10000   -e DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require&channel_binding=require"   -e CORS_ORIGIN="http://localhost:5173"   green-pulse-backend
```

확인:

```bash
curl http://localhost:3000/health
curl http://localhost:3000/api-docs-json
```

## 7. Render Web Service 생성

Render Dashboard에서:

1. New + 버튼 클릭
2. Web Service 선택
3. GitHub repo 연결
4. Runtime 또는 Language를 Docker로 선택
5. Dockerfile path: `./Dockerfile`
6. Health Check Path: `/health`
7. Environment Variables 설정

필수 환경변수:

| Key | Value |
|---|---|
| `DATABASE_URL` | Neon connection string |
| `DATABASE_SSL` | `true` |
| `CORS_ORIGIN` | 프론트 배포 URL |
| `NODE_ENV` | `production` |

Render Web Service는 `PORT` 환경변수를 제공합니다. 이 서버는 `PORT`를 읽고 `0.0.0.0`에 바인딩합니다.

## 8. Render Blueprint 사용

`render.yaml`도 추가되어 있습니다.

```yaml
services:
  - type: web
    name: green-pulse-backend
    runtime: docker
    healthCheckPath: /health
```

다만 `DATABASE_URL`과 `CORS_ORIGIN`은 secret 값이므로 Render Dashboard에서 직접 입력해야 합니다.

## 9. 배포 후 확인

Render 배포 URL이 아래와 같다고 가정합니다.

```text
https://green-pulse-backend.onrender.com
```

확인 URL:

```text
https://green-pulse-backend.onrender.com/health
https://green-pulse-backend.onrender.com/api-docs
https://green-pulse-backend.onrender.com/api/dashboard/overview
```

## 10. 포트폴리오에 쓰기 좋은 설명

```text
백엔드는 Nest.js로 구현하고 Docker 이미지로 패키징하여 Render에 배포했습니다.
PostgreSQL은 서버리스 DB인 Neon을 사용했으며, Python 모델은 실시간 실행 대신 배치로 사전 실행했습니다.
모델 결과 CSV는 Neon에 적재하고, API 서버는 사전 계산된 예측 이벤트와 월별 요약 데이터를 조회해 프론트엔드에 제공합니다.
```

핵심 포인트:

- Docker 기반 API 배포
- Neon PostgreSQL 연동
- 모델 추론과 API 서버 책임 분리
- 배치 결과 적재 후 대시보드 API 제공
- `/api-docs` Swagger 문서 제공
