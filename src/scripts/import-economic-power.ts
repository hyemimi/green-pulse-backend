import 'reflect-metadata';
import { createReadStream, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'csv-parse';
import { Pool } from 'pg';
import { createPgPoolConfig } from '../database/pg-options';

type EconomicPowerCsvRow = {
  timestamp?: string;
  operating_regime?: string;
  reactor_id?: string;
  fault_type?: string;
  wasted_power_kw?: string;
};

const projectRoot = resolve(__dirname, '../..');
const databaseUrl = process.env.DATABASE_URL;
const csvPath = resolve(
  projectRoot,
  process.env.ECONOMIC_POWER_CSV ?? './economic_power_calculation_5cols.csv',
);

if (!databaseUrl) {
  throw new Error('DATABASE_URL is required.');
}
if (!existsSync(csvPath)) {
  throw new Error(`Economic power CSV not found: ${csvPath}`);
}

const pool = new Pool(createPgPoolConfig(databaseUrl));

async function main() {
  const batch: unknown[][] = [];
  let importedRows = 0;

  console.log(`[IMPORT] economic_power_csv=${csvPath}`);
  await pool.query('BEGIN');

  try {
    for await (const row of readCsv(csvPath)) {
      const regime = required(row.operating_regime, 'operating_regime').toUpperCase();
      const faultType = requiredInteger(row.fault_type, 'fault_type');
      const wastedPowerKw = Math.max(requiredNumber(row.wasted_power_kw, 'wasted_power_kw'), 0);

      if (!['A', 'B'].includes(regime)) {
        throw new Error(`Invalid operating_regime: ${regime}`);
      }
      if (faultType < 0 || faultType > 4) {
        throw new Error(`Invalid fault_type: ${faultType}`);
      }

      batch.push([
        required(row.timestamp, 'timestamp'),
        regime,
        required(row.reactor_id, 'reactor_id'),
        faultType,
        wastedPowerKw,
      ]);

      if (batch.length >= 1000) {
        await insertBatch(batch);
        importedRows += batch.length;
        batch.length = 0;
        process.stdout.write(`\r[IMPORT] economic_power_readings rows=${importedRows}`);
      }
    }

    if (batch.length > 0) {
      await insertBatch(batch);
      importedRows += batch.length;
    }

    await pool.query('COMMIT');
  } catch (error) {
    await pool.query('ROLLBACK');
    throw error;
  }

  console.log(`\n[IMPORT] economic_power_readings complete rows=${importedRows}`);
  await pool.end();
}

async function insertBatch(rows: unknown[][]) {
  const columnsPerRow = 5;
  const values = rows.flat();
  const placeholders = rows
    .map((_, rowIndex) => {
      const offset = rowIndex * columnsPerRow;
      return `(${Array.from({ length: columnsPerRow }, (_value, columnIndex) => `$${offset + columnIndex + 1}`).join(', ')})`;
    })
    .join(', ');

  await pool.query(
    `
      INSERT INTO economic_power_readings (
        timestamp,
        operating_regime,
        reactor_id,
        fault_type,
        wasted_power_kw
      )
      VALUES ${placeholders}
      ON CONFLICT (reactor_id, timestamp)
      DO UPDATE SET
        operating_regime = EXCLUDED.operating_regime,
        fault_type = EXCLUDED.fault_type,
        wasted_power_kw = EXCLUDED.wasted_power_kw
    `,
    values,
  );
}

async function* readCsv(filePath: string): AsyncGenerator<EconomicPowerCsvRow> {
  const parser = createReadStream(filePath).pipe(
    parse({ columns: true, bom: true, skip_empty_lines: true, trim: true }),
  );

  for await (const row of parser) {
    yield row as EconomicPowerCsvRow;
  }
}

function required(value: string | undefined, column: string) {
  if (value === undefined || value === '') {
    throw new Error(`Missing required CSV value: ${column}`);
  }
  return value;
}

function requiredNumber(value: string | undefined, column: string) {
  const parsed = Number(required(value, column));
  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid numeric CSV value: ${column}=${value}`);
  }
  return parsed;
}

function requiredInteger(value: string | undefined, column: string) {
  const parsed = requiredNumber(value, column);
  if (!Number.isInteger(parsed)) {
    throw new Error(`Invalid integer CSV value: ${column}=${value}`);
  }
  return parsed;
}

main().catch(async (error: unknown) => {
  console.error(error);
  await pool.end();
  process.exit(1);
});
