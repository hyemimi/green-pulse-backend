# green-pulse-backend

AI 기반 촉매 공정 이상 상태 예측 솔루션 Green-Pulse의 백엔드 레포지토리입니다.

이 백엔드는 Python 모델을 실시간으로 실행하지 않습니다. Python 모델을 사전에 배치 실행하고, 생성된 결과 CSV를 PostgreSQL에 적재한 뒤 Nest.js API가 프론트엔드에 제공합니다.

## 개발 서버 실행 방법

현재 개발 환경에서는 로컬 PostgreSQL 대신 **Neon dev DB**를 바라보도록 설정해서 사용합니다.

### 1. 의존성 설치

```bash
npm install
```

### 2. `.env` 설정

프로젝트 루트에 `.env` 파일을 만들고 dev DB URL을 넣습니다.

```env
DATABASE_URL="NEON_DEV_DATABASE_URL"
DATABASE_SSL=true
PORT=3000
CORS_ORIGIN=http://localhost:5173
MODEL_WORKSPACE=./fault_run
```

`NEON_DEV_DATABASE_URL`에는 Neon dev DB connection string을 넣습니다. 비밀번호가 포함되어 있으므로 `.env`는 Git에 올리지 않습니다.

### 3. 환경변수 적용

zsh에서 `source .env`만 실행하면 `npm run ...` 자식 프로세스에 환경변수가 전달되지 않을 수 있습니다. 아래처럼 export 모드로 적용합니다.

```bash
set -a
source .env
set +a
```

적용 확인:

```bash
echo $DATABASE_URL
```

### 4. dev DB 테이블 생성

Neon dev DB에 테이블이 아직 없다면 실행합니다.

```bash
npm run db:migrate:node
```

### 5. 모델 결과 적재

`fault_run` 결과가 이미 있다면 바로 적재합니다.

```bash
npm run import:results
```

`fault_run` 폴더가 없다면 먼저 Python 모델을 실행합니다.

```bash
python3 fault_diagnosis_pipeline.py --workspace ./fault_run
npm run import:results
```

모델 결과 적재는 dev DB 기준으로 보통 한 번만 하면 됩니다. CSV나 모델 결과가 바뀌었거나 DB를 새로 만들었을 때만 다시 실행합니다.

### 6. 개발 서버 실행

```bash
npm run start:dev
```

기본 주소:

```text
http://localhost:3000
```

Swagger 문서:

```text
http://localhost:3000/api-docs
```

Health check:

```bash
curl http://localhost:3000/health
```

대시보드 API 확인:

```bash
curl http://localhost:3000/api/dashboard/overview
```

## 자주 쓰는 명령어

`.env`를 적용한 터미널에서는 아래처럼 짧게 실행할 수 있습니다.

```bash
npm run db:migrate:node
npm run import:results
npm run start:dev
```

환경변수를 명령 앞에 직접 붙여도 됩니다.

```bash
DATABASE_URL="NEON_DEV_DATABASE_URL" npm run db:migrate:node
DATABASE_URL="NEON_DEV_DATABASE_URL" MODEL_WORKSPACE=./fault_run npm run import:results
DATABASE_URL="NEON_DEV_DATABASE_URL" npm run start:dev
```

## 주요 문서

- [백엔드 Set Up](./docs/01-backend-setup.md)
- [백엔드 실행 방법](./docs/02-backend-run.md)
- [API 설명](./docs/03-api-reference.md)
- [EC2 배포 가이드](./docs/04-ec2-deployment.md)
- [Render + Neon + Docker 배포 가이드](./docs/05-render-neon-docker-deployment.md)
