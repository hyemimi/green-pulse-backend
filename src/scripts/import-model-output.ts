import 'reflect-metadata';
import { createReadStream, existsSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { parse } from 'csv-parse';
import { Pool } from 'pg';
import { createPgPoolConfig } from '../database/pg-options';

type CsvRecord = Record<string, string | undefined>;

type ReadingIndex = {
  timestamp: string;
  reactorId: string;
};

const projectRoot = resolve(__dirname, '../..');
const databaseUrl = process.env.DATABASE_URL;
const modelWorkspace = resolve(projectRoot, process.env.MODEL_WORKSPACE ?? './fault_run');
const rawCsvPath = resolve(projectRoot, 'chemical_process_timeseries.csv');

if (!databaseUrl) {
  throw new Error('DATABASE_URL is required. Example: DATABASE_URL=postgres://... npm run import:results');
}

const pool = new Pool(createPgPoolConfig(databaseUrl));

async function main() {
  const runId = makeRunId(modelWorkspace);

  assertFile(rawCsvPath);
  assertFile(resolve(modelWorkspace, 'integrated_arbitration_v2/final_events_all_holds.csv'));
  assertFile(resolve(modelWorkspace, 'integrated_arbitration_v2/episode_results_hold0.csv'));

  console.log(`[IMPORT] run_id=${runId}`);
  console.log(`[IMPORT] raw_csv=${rawCsvPath}`);
  console.log(`[IMPORT] model_workspace=${modelWorkspace}`);

  await pool.query('BEGIN');
  try {
    // 같은 runId를 다시 적재할 때 중복 데이터가 남지 않도록 run 단위로 삭제합니다.
    // reactor_readings는 원본 데이터 기준 테이블이라 여러 run이 공유하므로 삭제하지 않습니다.
    await pool.query('DELETE FROM model_runs WHERE id = $1', [runId]);
    await pool.query(
      `
        INSERT INTO model_runs (id, workspace_path, status, notes)
        VALUES ($1, $2, 'importing', $3)
      `,
      [runId, modelWorkspace, 'Imported from Python fault diagnosis pipeline outputs.'],
    );
    await pool.query('COMMIT');
  } catch (error) {
    await pool.query('ROLLBACK');
    throw error;
  }

  // 원본 CSV는 프론트 차트와 월별 집계의 기준 데이터입니다.
  // 이미 같은 reactor_id + timestamp가 있으면 건너뛰므로 반복 실행해도 안전합니다.
  const readingIndex = await importRawReadings(runId);

  await importFaultEvents(runId, readingIndex);
  await importEpisodeResults(runId);
  await importRunMetrics(runId);
  await rebuildMonthlySummaries(runId);
  await finalizeRun(runId);

  await pool.end();
  console.log('[IMPORT] done');
}

async function importRawReadings(runId: string) {
  console.log('[IMPORT] reactor_readings');

  const index = new Map<number, ReadingIndex>();
  const batch: unknown[][] = [];
  let rowIndex = 0;
  let dataStartAt: string | undefined;
  let dataEndAt: string | undefined;

  for await (const row of readCsv(rawCsvPath)) {
    index.set(rowIndex, {
      timestamp: required(row, 'timestamp'),
      reactorId: required(row, 'reactor_id'),
    });

    dataStartAt ??= required(row, 'timestamp');
    dataEndAt = required(row, 'timestamp');

    batch.push([
      required(row, 'timestamp'),
      nullableText(row.operating_regime),
      required(row, 'reactor_id'),
      nullableNumber(row.ambient_temp_effect),
      nullableNumber(row.reactor_temp),
      nullableNumber(row.reactor_pressure),
      nullableNumber(row.feed_flow_rate),
      nullableNumber(row.coolant_flow_rate),
      nullableNumber(row.agitator_speed_rpm),
      nullableNumber(row.reaction_rate),
      nullableNumber(row.conversion_rate),
      nullableNumber(row.selectivity),
      nullableNumber(row.yield_pct),
      nullableNumber(row.vibration_rms),
      nullableNumber(row.motor_current),
      nullableNumber(row.power_consumption_kw),
      nullableNumber(row.temp_setpoint),
      nullableNumber(row.pressure_setpoint),
      Number(required(row, 'fault_type')),
      nullableNumber(row.efficiency_loss_pct),
      nullableNumber(row.time_to_fault_min),
    ]);

    if (batch.length >= 1000) {
      await insertReadingBatch(batch);
      batch.length = 0;
      process.stdout.write(`\r[IMPORT] reactor_readings rows=${rowIndex + 1}`);
    }

    rowIndex += 1;
  }

  if (batch.length > 0) {
    await insertReadingBatch(batch);
  }

  console.log(`\n[IMPORT] reactor_readings indexed=${index.size}`);

  await pool.query(
    `
      UPDATE model_runs
      SET data_start_at = $1, data_end_at = $2
      WHERE id = $3
    `,
    [dataStartAt, dataEndAt, runId],
  );

  return index;
}

async function insertReadingBatch(rows: unknown[][]) {
  const columnsPerRow = 21;
  const values = rows.flat();
  const placeholders = rows
    .map((_, rowIndex) => {
      const offset = rowIndex * columnsPerRow;
      return `(${Array.from({ length: columnsPerRow }, (_v, colIndex) => `$${offset + colIndex + 1}`).join(', ')})`;
    })
    .join(', ');

  await pool.query(
    `
      INSERT INTO reactor_readings (
        timestamp,
        operating_regime,
        reactor_id,
        ambient_temp_effect,
        reactor_temp,
        reactor_pressure,
        feed_flow_rate,
        coolant_flow_rate,
        agitator_speed_rpm,
        reaction_rate,
        conversion_rate,
        selectivity,
        yield_pct,
        vibration_rms,
        motor_current,
        power_consumption_kw,
        temp_setpoint,
        pressure_setpoint,
        fault_type,
        efficiency_loss_pct,
        time_to_fault_min
      )
      VALUES ${placeholders}
      ON CONFLICT (reactor_id, timestamp) DO NOTHING
    `,
    values,
  );
}

async function importFaultEvents(runId: string, readingIndex: Map<number, ReadingIndex>) {
  console.log('[IMPORT] fault_events');

  const filePath = resolve(modelWorkspace, 'integrated_arbitration_v2/final_events_all_holds.csv');
  const batch: unknown[][] = [];
  let count = 0;

  for await (const row of readCsv(filePath)) {
    const eventIndex = Number(required(row, 'idx'));
    const indexedReading = readingIndex.get(eventIndex);

    batch.push([
      runId,
      eventIndex,
      indexedReading?.timestamp ?? null,
      required(row, 'reactor_id'),
      Number(required(row, 'pred_fault')),
      nullableInteger(row.true_fault),
      required(row, 'specialist'),
      nullableNumber(row.score),
      nullableInteger(row.hold) ?? 0,
      nullableInteger(row.episode_id),
    ]);

    if (batch.length >= 1000) {
      await insertFaultEventBatch(batch);
      count += batch.length;
      batch.length = 0;
    }
  }

  if (batch.length > 0) {
    await insertFaultEventBatch(batch);
    count += batch.length;
  }

  console.log(`[IMPORT] fault_events rows=${count}`);
}

async function insertFaultEventBatch(rows: unknown[][]) {
  const columnsPerRow = 10;
  const values = rows.flat();
  const placeholders = rows
    .map((_, rowIndex) => {
      const offset = rowIndex * columnsPerRow;
      return `(${Array.from({ length: columnsPerRow }, (_v, colIndex) => `$${offset + colIndex + 1}`).join(', ')})`;
    })
    .join(', ');

  await pool.query(
    `
      INSERT INTO fault_events (
        run_id,
        event_index,
        event_time,
        reactor_id,
        predicted_fault,
        true_fault,
        specialist,
        score,
        hold_min,
        episode_id
      )
      VALUES ${placeholders}
    `,
    values,
  );
}

async function importEpisodeResults(runId: string) {
  console.log('[IMPORT] episode_results');

  const arbitrationDir = resolve(modelWorkspace, 'integrated_arbitration_v2');
  const holdValues = [0, 5, 10, 15, 20, 25];
  let count = 0;

  for (const holdMin of holdValues) {
    const filePath = resolve(arbitrationDir, `episode_results_hold${holdMin}.csv`);
    if (!existsSync(filePath)) {
      continue;
    }

    for await (const row of readCsv(filePath)) {
      await pool.query(
        `
          INSERT INTO episode_results (
            run_id,
            hold_min,
            episode_id,
            fault,
            reactor_id,
            correct_delay_min,
            wrong_delay_min,
            wrong_before_correct
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
          ON CONFLICT (run_id, hold_min, episode_id)
          DO UPDATE SET
            fault = EXCLUDED.fault,
            reactor_id = EXCLUDED.reactor_id,
            correct_delay_min = EXCLUDED.correct_delay_min,
            wrong_delay_min = EXCLUDED.wrong_delay_min,
            wrong_before_correct = EXCLUDED.wrong_before_correct
        `,
        [
          runId,
          holdMin,
          Number(required(row, 'episode_id')),
          Number(required(row, 'fault')),
          required(row, 'reactor_id'),
          nullableNumber(row.correct_delay),
          nullableNumber(row.wrong_delay),
          parseBoolean(row.wrong_before_correct),
        ],
      );
      count += 1;
    }
  }

  console.log(`[IMPORT] episode_results rows=${count}`);
}

async function importRunMetrics(runId: string) {
  console.log('[IMPORT] run_metrics');

  await importMetricCsv(
    runId,
    'arbitration',
    resolve(modelWorkspace, 'integrated_arbitration_v2/arbitration_summary.csv'),
  );
  await importMetricCsv(
    runId,
    'integration',
    resolve(modelWorkspace, 'integrated_specialists_v1_outputs/integrated_overall_summary.csv'),
  );
}

async function importMetricCsv(runId: string, metricGroup: string, filePath: string) {
  if (!existsSync(filePath)) {
    console.warn(`[IMPORT] metric file skipped: ${filePath}`);
    return;
  }

  let rowNumber = 0;
  for await (const row of readCsv(filePath)) {
    for (const [name, rawValue] of Object.entries(row)) {
      const metricName = rowNumber === 0 ? name : `${name}_${rowNumber}`;
      const numericValue = nullableNumber(rawValue);

      await pool.query(
        `
          INSERT INTO run_metrics (run_id, metric_group, metric_name, metric_value, metric_text)
          VALUES ($1, $2, $3, $4, $5)
          ON CONFLICT (run_id, metric_group, metric_name)
          DO UPDATE SET
            metric_value = EXCLUDED.metric_value,
            metric_text = EXCLUDED.metric_text
        `,
        [runId, metricGroup, metricName, numericValue, numericValue === null ? nullableText(rawValue) : null],
      );
    }
    rowNumber += 1;
  }
}

async function rebuildMonthlySummaries(runId: string) {
  console.log('[IMPORT] monthly_summaries');

  await pool.query('DELETE FROM monthly_summaries WHERE run_id = $1', [runId]);

  // 월별 센서 평균과 fault 비중은 원본 readings에서, 예측 이벤트 수는 모델 결과에서 집계합니다.
  // reactor_id를 NULL로 둔 전체 요약도 같이 만들면 프론트에서 전체/개별 Reactor 뷰를 쉽게 전환할 수 있습니다.
  await pool.query(
    `
      INSERT INTO monthly_summaries (
        run_id,
        month,
        reactor_id,
        reading_count,
        fault_reading_count,
        normal_reading_count,
        predicted_event_count,
        avg_reactor_temp,
        avg_pressure,
        avg_efficiency_loss_pct
      )
      SELECT
        $1 AS run_id,
        DATE_TRUNC('month', r.timestamp)::date AS month,
        r.reactor_id,
        COUNT(*)::int AS reading_count,
        COUNT(*) FILTER (WHERE r.fault_type <> 0)::int AS fault_reading_count,
        COUNT(*) FILTER (WHERE r.fault_type = 0)::int AS normal_reading_count,
        COUNT(e.id)::int AS predicted_event_count,
        AVG(r.reactor_temp)::float AS avg_reactor_temp,
        AVG(r.reactor_pressure)::float AS avg_pressure,
        AVG(r.efficiency_loss_pct)::float AS avg_efficiency_loss_pct
      FROM reactor_readings r
      LEFT JOIN fault_events e
        ON e.run_id = $1
       AND e.hold_min = 0
       AND e.reactor_id = r.reactor_id
       AND DATE_TRUNC('minute', e.event_time) = DATE_TRUNC('minute', r.timestamp)
      GROUP BY DATE_TRUNC('month', r.timestamp)::date, r.reactor_id
    `,
    [runId],
  );

  await pool.query(
    `
      INSERT INTO monthly_summaries (
        run_id,
        month,
        reactor_id,
        reading_count,
        fault_reading_count,
        normal_reading_count,
        predicted_event_count,
        avg_reactor_temp,
        avg_pressure,
        avg_efficiency_loss_pct
      )
      SELECT
        $1 AS run_id,
        DATE_TRUNC('month', r.timestamp)::date AS month,
        NULL AS reactor_id,
        COUNT(*)::int AS reading_count,
        COUNT(*) FILTER (WHERE r.fault_type <> 0)::int AS fault_reading_count,
        COUNT(*) FILTER (WHERE r.fault_type = 0)::int AS normal_reading_count,
        COUNT(e.id)::int AS predicted_event_count,
        AVG(r.reactor_temp)::float AS avg_reactor_temp,
        AVG(r.reactor_pressure)::float AS avg_pressure,
        AVG(r.efficiency_loss_pct)::float AS avg_efficiency_loss_pct
      FROM reactor_readings r
      LEFT JOIN fault_events e
        ON e.run_id = $1
       AND e.hold_min = 0
       AND e.reactor_id = r.reactor_id
       AND DATE_TRUNC('minute', e.event_time) = DATE_TRUNC('minute', r.timestamp)
      GROUP BY DATE_TRUNC('month', r.timestamp)::date
    `,
    [runId],
  );
}

async function finalizeRun(runId: string) {
  await pool.query(
    `
      UPDATE model_runs
      SET status = 'imported'
      WHERE id = $1
    `,
    [runId],
  );
}

async function* readCsv(filePath: string): AsyncGenerator<CsvRecord> {
  const parser = createReadStream(filePath).pipe(
    parse({
      columns: true,
      bom: true,
      skip_empty_lines: true,
      trim: true,
    }),
  );

  for await (const record of parser) {
    yield record as CsvRecord;
  }
}

function assertFile(filePath: string) {
  if (!existsSync(filePath)) {
    throw new Error(`Required file not found: ${filePath}`);
  }
}

function makeRunId(workspacePath: string) {
  // 같은 결과 폴더를 다시 import하면 같은 runId를 쓰게 해서 재현 가능한 데이터 적재가 됩니다.
  return basename(resolve(workspacePath)).replace(/[^a-zA-Z0-9_-]/g, '_');
}

function required(row: CsvRecord, key: string) {
  const value = row[key];
  if (value === undefined || value === '') {
    throw new Error(`Missing required CSV column/value: ${key}`);
  }
  return value;
}

function nullableText(value: string | undefined) {
  return value === undefined || value === '' || value === 'nan' ? null : value;
}

function nullableNumber(value: string | undefined) {
  if (value === undefined || value === '' || value.toLowerCase() === 'nan') {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function nullableInteger(value: string | undefined) {
  const parsed = nullableNumber(value);
  return parsed === null ? null : Math.trunc(parsed);
}

function parseBoolean(value: string | undefined) {
  if (!value) {
    return false;
  }

  return ['true', '1', 'yes'].includes(value.toLowerCase());
}

main().catch(async (error: unknown) => {
  console.error(error);
  await pool.end();
  process.exit(1);
});
