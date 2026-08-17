import type { PoolConfig } from 'pg';

export function createPgPoolConfig(connectionString: string): PoolConfig {
  const hasSslMode = connectionString.includes('sslmode=');
  const isNeon = connectionString.includes('.neon.tech');
  const forceSsl = process.env.DATABASE_SSL === 'true';

  // Neon은 TLS 연결이 필수입니다. Neon Dashboard에서 복사한 URL에는 보통
  // ?sslmode=require 가 포함되어 있으므로 그 경우 node-postgres가 URL 값을 해석하게 둡니다.
  // sslmode가 없는 Neon URL이나 DATABASE_SSL=true 환경에서는 SSL을 명시적으로 켭니다.
  return {
    connectionString,
    ssl: !hasSslMode && (isNeon || forceSsl) ? { rejectUnauthorized: true } : undefined,
  };
}
