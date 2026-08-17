import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service';

type MonthlyQuery = {
  runId?: string;
  from?: string;
  to?: string;
  reactorId?: string;
};

type EventQuery = MonthlyQuery & {
  holdMin: number;
  limit: number;
};

type ReadingQuery = {
  reactorId: string;
  from?: string;
  to?: string;
  limit: number;
};

@Injectable()
export class DashboardService {
  constructor(private readonly db: DatabaseService) {}

  async getModelRuns() {
    const { rows } = await this.db.query(`
      SELECT
        id,
        workspace_path AS "workspacePath",
        status,
        data_start_at AS "dataStartAt",
        data_end_at AS "dataEndAt",
        imported_at AS "importedAt",
        notes
      FROM model_runs
      ORDER BY imported_at DESC
    `);

    return rows;
  }

  async getOverview(runId?: string, holdMin = 0) {
    const resolvedRunId = await this.resolveRunId(runId);

    // overview는 대시보드 첫 화면에서 쓸 핵심 KPI만 묶어 반환합니다.
    // 프론트가 여러 API를 동시에 호출하지 않아도 되도록 일부 집계를 서버에서 처리합니다.
    const [runResult, monthlyResult, eventResult, episodeResult, latestMetricsResult] = await Promise.all([
      this.db.query(
        `
          SELECT
            id,
            workspace_path AS "workspacePath",
            status,
            data_start_at AS "dataStartAt",
            data_end_at AS "dataEndAt",
            imported_at AS "importedAt",
            notes
          FROM model_runs
          WHERE id = $1
        `,
        [resolvedRunId],
      ),
      this.db.query(
        `
          SELECT
            COALESCE(SUM(reading_count), 0)::int AS "readingCount",
            COALESCE(SUM(fault_reading_count), 0)::int AS "faultReadingCount",
            COALESCE(SUM(normal_reading_count), 0)::int AS "normalReadingCount",
            COUNT(DISTINCT month)::int AS "monthCount",
            COUNT(DISTINCT reactor_id)::int AS "reactorCount"
          FROM monthly_summaries
          WHERE run_id = $1
        `,
        [resolvedRunId],
      ),
      this.db.query(
        `
          SELECT
            COUNT(*)::int AS "eventCount",
            COUNT(*) FILTER (WHERE predicted_fault = true_fault)::int AS "correctEventCount",
            AVG(score)::float AS "avgScore"
          FROM fault_events
          WHERE run_id = $1 AND hold_min = $2
        `,
        [resolvedRunId, holdMin],
      ),
      this.db.query(
        `
          SELECT
            COUNT(*)::int AS "episodeCount",
            COUNT(*) FILTER (WHERE correct_delay_min IS NOT NULL)::int AS "detectedEpisodeCount",
            COUNT(*) FILTER (WHERE correct_delay_min <= 15)::int AS "within15Count",
            COUNT(*) FILTER (WHERE correct_delay_min <= 30)::int AS "within30Count",
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY correct_delay_min)::float AS "medianDelayMin",
            AVG(CASE WHEN wrong_before_correct THEN 1 ELSE 0 END)::float AS "wrongBeforeCorrectRate"
          FROM episode_results
          WHERE run_id = $1 AND hold_min = $2
        `,
        [resolvedRunId, holdMin],
      ),
      this.db.query(
        `
          SELECT metric_group AS "group", metric_name AS "name", metric_value AS "value", metric_text AS "text"
          FROM run_metrics
          WHERE run_id = $1
          ORDER BY metric_group, metric_name
        `,
        [resolvedRunId],
      ),
    ]);

    return {
      run: runResult.rows[0],
      data: monthlyResult.rows[0],
      events: eventResult.rows[0],
      episodes: episodeResult.rows[0],
      metrics: latestMetricsResult.rows,
    };
  }

  async getMonthlySummaries(query: MonthlyQuery) {
    const runId = await this.resolveRunId(query.runId);
    const conditions = ['run_id = $1'];
    const params: unknown[] = [runId];

    if (query.from) {
      params.push(query.from);
      conditions.push(`month >= $${params.length}`);
    }

    if (query.to) {
      params.push(query.to);
      conditions.push(`month <= $${params.length}`);
    }

    if (query.reactorId) {
      params.push(query.reactorId);
      conditions.push(`reactor_id = $${params.length}`);
    }

    const { rows } = await this.db.query(
      `
        SELECT
          month,
          reactor_id AS "reactorId",
          reading_count AS "readingCount",
          fault_reading_count AS "faultReadingCount",
          normal_reading_count AS "normalReadingCount",
          predicted_event_count AS "predictedEventCount",
          avg_reactor_temp AS "avgReactorTemp",
          avg_pressure AS "avgPressure",
          avg_efficiency_loss_pct AS "avgEfficiencyLossPct"
        FROM monthly_summaries
        WHERE ${conditions.join(' AND ')}
        ORDER BY month, reactor_id NULLS FIRST
      `,
      params,
    );

    return rows;
  }

  async getFaultEvents(query: EventQuery) {
    const runId = await this.resolveRunId(query.runId);
    const conditions = ['run_id = $1', 'hold_min = $2'];
    const params: unknown[] = [runId, query.holdMin];

    if (query.reactorId) {
      params.push(query.reactorId);
      conditions.push(`reactor_id = $${params.length}`);
    }

    if (query.from) {
      params.push(query.from);
      conditions.push(`event_time >= $${params.length}`);
    }

    if (query.to) {
      params.push(query.to);
      conditions.push(`event_time <= $${params.length}`);
    }

    params.push(Math.min(Math.max(query.limit || 200, 1), 1000));

    const { rows } = await this.db.query(
      `
        SELECT
          id,
          event_index AS "eventIndex",
          event_time AS "eventTime",
          reactor_id AS "reactorId",
          predicted_fault AS "predictedFault",
          true_fault AS "trueFault",
          specialist,
          score,
          hold_min AS "holdMin",
          episode_id AS "episodeId"
        FROM fault_events
        WHERE ${conditions.join(' AND ')}
        ORDER BY event_time NULLS LAST, event_index
        LIMIT $${params.length}
      `,
      params,
    );

    return rows;
  }

  async getEpisodeResults(runId?: string, holdMin = 0) {
    const resolvedRunId = await this.resolveRunId(runId);
    const { rows } = await this.db.query(
      `
        SELECT
          episode_id AS "episodeId",
          fault,
          reactor_id AS "reactorId",
          correct_delay_min AS "correctDelayMin",
          wrong_delay_min AS "wrongDelayMin",
          wrong_before_correct AS "wrongBeforeCorrect"
        FROM episode_results
        WHERE run_id = $1 AND hold_min = $2
        ORDER BY episode_id
      `,
      [resolvedRunId, holdMin],
    );

    return rows;
  }

  async getReactorReadings(query: ReadingQuery) {
    const conditions = ['reactor_id = $1'];
    const params: unknown[] = [query.reactorId];

    if (query.from) {
      params.push(query.from);
      conditions.push(`timestamp >= $${params.length}`);
    }

    if (query.to) {
      params.push(query.to);
      conditions.push(`timestamp <= $${params.length}`);
    }

    params.push(Math.min(Math.max(query.limit || 1440, 1), 10000));

    const { rows } = await this.db.query(
      `
        SELECT
          timestamp,
          reactor_id AS "reactorId",
          reactor_temp AS "reactorTemp",
          reactor_pressure AS "reactorPressure",
          feed_flow_rate AS "feedFlowRate",
          coolant_flow_rate AS "coolantFlowRate",
          agitator_speed_rpm AS "agitatorSpeedRpm",
          vibration_rms AS "vibrationRms",
          motor_current AS "motorCurrent",
          power_consumption_kw AS "powerConsumptionKw",
          fault_type AS "faultType",
          efficiency_loss_pct AS "efficiencyLossPct"
        FROM reactor_readings
        WHERE ${conditions.join(' AND ')}
        ORDER BY timestamp
        LIMIT $${params.length}
      `,
      params,
    );

    return rows;
  }

  private async resolveRunId(runId?: string) {
    if (runId) {
      return runId;
    }

    const { rows } = await this.db.query<{ id: string }>(`
      SELECT id
      FROM model_runs
      ORDER BY imported_at DESC
      LIMIT 1
    `);

    if (!rows[0]) {
      throw new Error('No imported model run found. Run npm run import:results first.');
    }

    return rows[0].id;
  }
}
