# 04. EC2 배포 설정 가이드

EC2 같은 서버에 배포할 때도 구조는 로컬과 같습니다.

```text
PostgreSQL 준비
  -> DB migration
  -> Python 모델 결과 적재
  -> Nest.js 서버 실행
  -> Nginx 또는 로드밸런서로 외부 공개
```

## 1. 권장 배포 구조

포트폴리오 프로젝트 기준 권장 구조:

```text
EC2
  - Node.js / Nest.js API
  - Python 모델 파일
  - fault_run 모델 결과 폴더

PostgreSQL
  - 같은 EC2에 설치하거나
  - AWS RDS PostgreSQL 사용

Nginx
  - api.example.com -> localhost:3000 reverse proxy
```

운영 느낌을 더 내고 싶다면 PostgreSQL은 EC2 내부 설치보다 RDS를 추천합니다.
단, 비용과 관리 난이도를 줄이고 싶다면 EC2 내부 PostgreSQL도 포트폴리오에는 충분합니다.

## 2. 서버 환경변수

EC2에서는 `.env`를 서버에 두거나 systemd 환경변수로 관리합니다.

예시:

```env
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/green_pulse
PORT=3000
CORS_ORIGIN=https://your-frontend-domain.com
MODEL_WORKSPACE=./fault_run
```

주의:

- `DATABASE_URL`에는 실제 DB 계정과 비밀번호를 넣습니다.
- `.env`는 Git에 올리지 않습니다.
- 프론트 도메인이 정해지면 `CORS_ORIGIN`을 해당 도메인으로 제한합니다.

## 3. EC2 초기 설치 예시

Ubuntu 기준 예시입니다.

```bash
sudo apt update
sudo apt install -y nodejs npm python3 python3-pip postgresql postgresql-contrib nginx
```

Node.js는 배포 환경에 따라 NodeSource 또는 nvm으로 최신 LTS를 설치하는 것이 더 좋습니다.

Python 패키지:

```bash
python3 -m pip install pandas numpy scikit-learn xgboost numba matplotlib
```

프로젝트 의존성:

```bash
npm ci
```

빌드:

```bash
npm run build
```

## 4. DB 준비

EC2 내부 PostgreSQL을 쓰는 경우:

```bash
sudo -u postgres createdb green_pulse
```

별도 계정을 만들고 싶다면:

```bash
sudo -u postgres createuser green_pulse_user
sudo -u postgres psql
```

```sql
ALTER USER green_pulse_user WITH PASSWORD 'strong_password';
GRANT ALL PRIVILEGES ON DATABASE green_pulse TO green_pulse_user;
\q
```

그 다음:

```bash
DATABASE_URL=postgres://green_pulse_user:strong_password@localhost:5432/green_pulse npm run db:migrate
```

RDS를 쓰는 경우:

```bash
DATABASE_URL=postgres://USER:PASSWORD@RDS_ENDPOINT:5432/green_pulse npm run db:migrate
```

## 5. 모델 실행과 적재

서버에서 모델을 직접 실행하는 경우:

```bash
python3 fault_diagnosis_pipeline.py --workspace ./fault_run
```

그 다음 적재:

```bash
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/green_pulse MODEL_WORKSPACE=./fault_run npm run import:results
```

이 적재 작업은 서버 또는 DB 기준으로 보통 한 번만 실행합니다.

다시 실행해야 하는 경우:

- 새 서버를 띄운 경우
- DB를 새로 만든 경우
- 모델 결과를 새로 생성한 경우
- CSV 데이터가 바뀐 경우
- 모델 로직을 수정해서 재실험한 경우

Nest.js API 서버를 재시작하는 것만으로는 다시 실행할 필요가 없습니다.

## 6. 서버 실행 방식

개발처럼 직접 실행:

```bash
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/green_pulse npm run start:dev
```

실제 배포에서는 빌드 후 Node로 실행하는 것이 좋습니다.

```bash
npm run build
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/green_pulse PORT=3000 node dist/main.js
```

## 7. systemd 서비스 예시

`/etc/systemd/system/green-pulse-api.service`

```ini
[Unit]
Description=Green-Pulse Nest.js API
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/green-pulse-backend
Environment=NODE_ENV=production
Environment=PORT=3000
Environment=DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/green_pulse
Environment=CORS_ORIGIN=https://your-frontend-domain.com
ExecStart=/usr/bin/node dist/main.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

적용:

```bash
sudo systemctl daemon-reload
sudo systemctl enable green-pulse-api
sudo systemctl start green-pulse-api
sudo systemctl status green-pulse-api
```

로그 확인:

```bash
journalctl -u green-pulse-api -f
```

## 8. Nginx reverse proxy 예시

`/etc/nginx/sites-available/green-pulse-api`

```nginx
server {
    listen 80;
    server_name api.your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

활성화:

```bash
sudo ln -s /etc/nginx/sites-available/green-pulse-api /etc/nginx/sites-enabled/green-pulse-api
sudo nginx -t
sudo systemctl reload nginx
```

HTTPS는 Certbot을 사용할 수 있습니다.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.your-domain.com
```

## 9. 배포 시 보안 체크리스트

- `.env`를 Git에 올리지 않습니다.
- PostgreSQL 포트 `5432`를 외부 전체에 열지 않습니다.
- RDS를 쓰는 경우 EC2 Security Group에서만 접근 가능하게 제한합니다.
- `CORS_ORIGIN`을 실제 프론트 도메인으로 제한합니다.
- 서버 재시작 후에도 API가 살아나도록 systemd 또는 PM2를 사용합니다.
- 모델 결과 CSV와 원본 CSV의 출처와 기준 기간을 README 또는 프론트에 명시합니다.

## 10. 포트폴리오 설명 포인트

배포 설명에서는 아래 흐름을 강조하면 좋습니다.

```text
제한된 기간의 공정 시계열 데이터를 대상으로 Python 모델을 배치 실행하고,
생성된 fault event와 월별 summary를 PostgreSQL에 적재했습니다.
Nest.js API는 실시간 추론 대신 사전 계산된 모델 결과를 빠르게 제공하며,
프론트엔드는 이를 기반으로 AI 진단 대시보드를 구성합니다.
```
