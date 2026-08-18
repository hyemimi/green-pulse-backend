import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DashboardModule } from './dashboard/dashboard.module';
import { DatabaseModule } from './database/database.module';
import { HealthController } from './health.controller';
import { EsgModule } from './esg/esg.module';
import { ReportsModule } from './reports/reports.module';

@Module({
  imports: [
    // .env 파일을 기준으로 DB 연결, CORS, 포트 등을 관리합니다.
    // 포트폴리오/배포 환경에서 설정값만 바꾸면 같은 코드를 재사용할 수 있습니다.
    ConfigModule.forRoot({ isGlobal: true }),
    DatabaseModule,
    DashboardModule,
    EsgModule,
    ReportsModule,
  ],
  controllers: [HealthController],
})
export class AppModule {}
