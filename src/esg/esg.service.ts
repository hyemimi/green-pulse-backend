import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DatabaseService } from '../database/database.service';
import { convertEnergySaving, EsgConversionFactors } from './esg-calculator';

export type EsgQuery = {
  runId?: string;
  from?: string;
  to?: string;
  reactorId?: string;
};

type EnergyTotalRow = {
  energySavedKwh: number | string;
  savingRecordCount: number;
};

type MonthlyEnergyRow = {
  month: string;
  energySavedKwh: number | string;
  savingRecordCount: number;
};

@Injectable()
export class EsgService {
  private readonly factors: EsgConversionFactors;

  constructor(
    private readonly db: DatabaseService,
    private readonly config: ConfigService,
  ) {
    this.factors = {
      co2KgPerKwh: this.numberConfig('CO2_FACTOR_KG_PER_KWH', 0.4541),
      paperCupCo2Kg: this.numberConfig('PAPER_CUP_CO2_KG', 0.0452),
      carCo2KgPerKm: this.numberConfig('CAR_CO2_KG_PER_KM', 0.14),
      pineTreeCo2KgPerYear: this.numberConfig('PINE_TREE_CO2_KG_PER_YEAR', 125),
      tissueRollCo2Kg: this.numberConfig('TISSUE_ROLL_CO2_KG', 0.288),
      electricityPriceKrwPerKwh: this.numberConfig('ELECTRICITY_PRICE_KRW_PER_KWH', 0),
      annualEnergyTargetKwh: this.numberConfig('ANNUAL_ENERGY_TARGET_KWH', 0),
      version: this.config.get<string>('ESG_FACTOR_VERSION') ?? 'project-draft-v1',
    };
  }

  getConversionFactors() {
    return {
      measurementMode: 'ESTIMATED',
      factors: this.factors,
      notice: 'These factors are configurable project assumptions and must be confirmed before production use.',
    };
  }

  async getSummary(query: EsgQuery) {
    const runId = await this.resolveRunId(query.runId);
    const { conditions, params } = this.buildConditions(runId, query);
    const { rows } = await this.db.query<EnergyTotalRow>(
      `
        SELECT
          COALESCE(SUM(energy_saved_kwh), 0)::float AS "energySavedKwh",
          COUNT(*)::int AS "savingRecordCount"
        FROM esg_energy_savings
        WHERE ${conditions.join(' AND ')}
      `,
      params,
    );
    const energySavedKwh = Number(rows[0]?.energySavedKwh ?? 0);

    return {
      runId,
      period: { from: query.from ?? null, to: query.to ?? null },
      reactorId: query.reactorId ?? null,
      measurementMode: 'ESTIMATED',
      savingRecordCount: rows[0]?.savingRecordCount ?? 0,
      ...convertEnergySaving(energySavedKwh, this.factors),
      factorVersion: this.factors.version,
    };
  }

  async getMonthly(query: EsgQuery) {
    const runId = await this.resolveRunId(query.runId);
    const { conditions, params } = this.buildConditions(runId, query);
    const { rows } = await this.db.query<MonthlyEnergyRow>(
      `
        SELECT
          DATE_TRUNC('month', timestamp)::date AS month,
          COALESCE(SUM(energy_saved_kwh), 0)::float AS "energySavedKwh",
          COUNT(*)::int AS "savingRecordCount"
        FROM esg_energy_savings
        WHERE ${conditions.join(' AND ')}
        GROUP BY DATE_TRUNC('month', timestamp)::date
        ORDER BY month
      `,
      params,
    );

    let cumulativeEnergySavedKwh = 0;
    return rows.map((row) => {
      const energySavedKwh = Number(row.energySavedKwh);
      cumulativeEnergySavedKwh += energySavedKwh;

      return {
        month: row.month,
        savingRecordCount: row.savingRecordCount,
        ...convertEnergySaving(energySavedKwh, this.factors),
        cumulativeEnergySavedKwh,
        cumulativeCo2ReducedKg: cumulativeEnergySavedKwh * this.factors.co2KgPerKwh,
        cumulativeTargetAchievementPct:
          this.factors.annualEnergyTargetKwh > 0
            ? (cumulativeEnergySavedKwh / this.factors.annualEnergyTargetKwh) * 100
            : null,
        factorVersion: this.factors.version,
      };
    });
  }

  private buildConditions(runId: string, query: EsgQuery) {
    const conditions = ['run_id = $1'];
    const params: unknown[] = [runId];

    if (query.from) {
      params.push(query.from);
      conditions.push(`timestamp >= $${params.length}::date`);
    }
    if (query.to) {
      params.push(query.to);
      conditions.push(`timestamp < ($${params.length}::date + INTERVAL '1 day')`);
    }
    if (query.reactorId) {
      params.push(query.reactorId);
      conditions.push(`reactor_id = $${params.length}`);
    }

    return { conditions, params };
  }

  private async resolveRunId(runId?: string) {
    if (runId) {
      return runId;
    }

    const { rows } = await this.db.query<{ id: string }>(`
      SELECT id FROM model_runs ORDER BY imported_at DESC LIMIT 1
    `);
    if (!rows[0]) {
      throw new Error('No imported model run found. Run npm run import:results first.');
    }
    return rows[0].id;
  }

  private numberConfig(name: string, defaultValue: number) {
    const raw = this.config.get<string>(name);
    if (raw === undefined || raw === '') {
      return defaultValue;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed < 0) {
      throw new Error(`${name} must be a non-negative number.`);
    }
    return parsed;
  }
}
