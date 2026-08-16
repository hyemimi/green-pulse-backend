import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Pool, QueryResultRow } from 'pg';

@Injectable()
export class DatabaseService implements OnModuleDestroy {
  private readonly pool: Pool;

  constructor(config: ConfigService) {
    const connectionString = config.get<string>('DATABASE_URL');

    if (!connectionString) {
      throw new Error('DATABASE_URL is required. Copy .env.example to .env and set DATABASE_URL.');
    }

    // pg Pool을 직접 쓰는 이유:
    // 이 프로젝트는 복잡한 도메인 쓰기보다 CSV/모델 결과 적재와 읽기 API가 중심입니다.
    // ORM을 크게 얹기보다 SQL을 명시해두는 편이 데이터 흐름을 설명하기 쉽습니다.
    this.pool = new Pool({ connectionString });
  }

  async query<T extends QueryResultRow = QueryResultRow>(text: string, params: unknown[] = []) {
    return this.pool.query<T>(text, params);
  }

  async onModuleDestroy() {
    await this.pool.end();
  }
}
