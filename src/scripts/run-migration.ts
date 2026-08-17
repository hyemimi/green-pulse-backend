import 'reflect-metadata';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { Pool } from 'pg';
import { createPgPoolConfig } from '../database/pg-options';

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error('DATABASE_URL is required. Example: DATABASE_URL=postgresql://... npm run db:migrate:node');
}

const migrationsDir = resolve(__dirname, '../../database/migrations');
const migrationFiles = readdirSync(migrationsDir)
  .filter((fileName) => fileName.endsWith('.sql'))
  .sort();
const pool = new Pool(createPgPoolConfig(databaseUrl));

async function main() {
  // Render/Neon 배포 환경에서는 psql CLI가 없을 수 있으므로 Node pg client로 SQL migration을 실행합니다.
  // migration SQL은 CREATE TABLE IF NOT EXISTS 기반이라 여러 번 실행해도 안전합니다.
  for (const fileName of migrationFiles) {
    const migrationPath = resolve(migrationsDir, fileName);
    const sql = readFileSync(migrationPath, 'utf8');
    await pool.query(sql);
    console.log(`[MIGRATION] applied ${migrationPath}`);
  }
  await pool.end();
  console.log(`[MIGRATION] completed files=${migrationFiles.length}`);
}

main().catch(async (error: unknown) => {
  console.error(error);
  await pool.end();
  process.exit(1);
});
