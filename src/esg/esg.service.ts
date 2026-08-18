import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DatabaseService } from '../database/database.service';
import { convertEnergySaving, EsgConversionFactors } from './esg-calculator';

export type EsgQuery = {
  runId?: string;
  from?: string;
  to?: string;
  reactorId?: string;
  holdMin: number;
  playbackMinute?: number;
};

export type PowerSavingQuery = {
  reactorId: string;
  predictedFault: string;
  onsetTimestamp: string;
  detectTimestamp?: string;
  detectMinute?: number;
};

type Regime = 'A' | 'B';

type DetectionLossRow = {
  operatingRegime: string;
  actualFaultAtDetection: number;
  wastedPowerKwAtDetection: number | string;
  actualLossUntilDetectionKwh: number | string;
  integratedMinutes: number;
};

type EpisodeLossRow = DetectionLossRow & {
  episodeId: number;
  reactorId: string;
  predictedFault: number;
  onsetTimestamp: Date;
  detectTimestamp: Date;
  detectMinute: number | string;
};

type QuarterTargetRow = {
  quarter: number;
  targetKwh: number | string;
  updatedAt: Date;
};

type TrainingEpisodeRow = {
  reactorId: string;
  operatingRegime: string;
  fault: number;
  onsetTimestamp: Date;
  actualLossUntilDetectionKwh: number | string;
};

const UNMITIGATED_LOSS_KWH: Record<Regime, Record<number, number>> = {
  A: { 1: 3.520724, 2: 66.480152, 3: 0.684389, 4: 36.743387 },
  B: { 1: 3.910796, 2: 38.773997, 3: 2.894215, 4: 24.382986 },
};

const CALCULATION_METHOD =
  'saved = regime/fault unmitigated loss - SUM(wasted_power_kw from onset inclusive to detection exclusive) / 60';

@Injectable()
export class EsgService {
  private readonly factors: EsgConversionFactors;

  constructor(
    private readonly db: DatabaseService,
    private readonly config: ConfigService,
  ) {
    this.factors = {
      co2KgPerKwh: this.numberConfig('CO2_FACTOR_KG_PER_KWH', 0.5304),
      paperCupCo2Kg: this.numberConfig('PAPER_CUP_CO2_KG', 0.0452),
      carCo2KgPerKm: this.numberConfig('CAR_CO2_KG_PER_KM', 0.14),
      pineTreeCo2KgPerYear: this.numberConfig('PINE_TREE_CO2_KG_PER_YEAR', 125),
      tissueRollCo2Kg: this.numberConfig('TISSUE_ROLL_CO2_KG', 0.288),
      electricityPriceKrwPerKwh: this.numberConfig('ELECTRICITY_PRICE_KRW_PER_KWH', 150),
      annualEnergyTargetKwh: this.numberConfig('ANNUAL_ENERGY_TARGET_KWH', 0),
      version: this.config.get<string>('ESG_FACTOR_VERSION') ?? 'economic-power-csv-v2',
    };
  }

  getConversionFactors() {
    return {
      measurementMode: 'ESTIMATED',
      factors: this.factors,
      powerSavingCalculation: {
        method: CALCULATION_METHOD,
        dataSource: 'economic_power_calculation_5cols.csv imported into economic_power_readings',
        wastedPowerKwFormula: 'Use the CSV wasted_power_kw value directly',
        intervalMinutes: 1,
        unmitigatedLossKwh: UNMITIGATED_LOSS_KWH,
      },
    };
  }

  async getPowerSaving(query: PowerSavingQuery) {
    if (!query.reactorId?.trim()) {
      throw new BadRequestException('reactorId is required.');
    }
    const fault = this.normalizeFault(query.predictedFault);
    const onset = this.parseTimestamp(query.onsetTimestamp, 'onsetTimestamp');
    const detect = this.resolveDetectionTimestamp(onset, query);

    if (detect.getTime() < onset.getTime()) {
      throw new BadRequestException('detectTimestamp must not be earlier than onsetTimestamp.');
    }

    const { rows } = await this.db.query<DetectionLossRow>(
      `
        SELECT
          COALESCE(d.operating_regime, LEFT(d.reactor_id, 1)) AS "operatingRegime",
          d.fault_type::int AS "actualFaultAtDetection",
          GREATEST(COALESCE(d.wasted_power_kw, 0), 0)::float AS "wastedPowerKwAtDetection",
          COALESCE(loss.actual_loss_kwh, 0)::float AS "actualLossUntilDetectionKwh",
          COALESCE(loss.integrated_minutes, 0)::int AS "integratedMinutes"
        FROM economic_power_readings d
        CROSS JOIN LATERAL (
          SELECT
            COUNT(*)::int AS integrated_minutes,
            SUM(GREATEST(COALESCE(r.wasted_power_kw, 0), 0)) / 60.0 AS actual_loss_kwh
          FROM economic_power_readings r
          WHERE r.reactor_id = d.reactor_id
            AND r.timestamp >= $3::timestamptz
            AND r.timestamp < $2::timestamptz
        ) loss
        WHERE d.reactor_id = $1
          AND d.timestamp = $2::timestamptz
      `,
      [query.reactorId, detect.toISOString(), onset.toISOString()],
    );

    const row = rows[0];
    if (!row) {
      throw new NotFoundException(
        `No reactor reading found for ${query.reactorId} at ${detect.toISOString()}.`,
      );
    }

    return this.toPowerSavingResult({
      reactorId: query.reactorId,
      regime: this.normalizeRegime(row.operatingRegime),
      fault,
      actualFaultAtDetection: row.actualFaultAtDetection,
      onset,
      detect,
      integratedMinutes: row.integratedMinutes,
      wastedPowerKwAtDetection: Number(row.wastedPowerKwAtDetection),
      actualLossUntilDetectionKwh: Number(row.actualLossUntilDetectionKwh),
    });
  }

  async getSummary(query: EsgQuery) {
    this.validateEsgQuery(query);
    const runId = await this.resolveRunId(query.runId);
    const episodes = await this.getEpisodeSavings(runId, query);
    const energySavedKwh = episodes.reduce((sum, episode) => sum + episode.savedKwh, 0);
    const totalUnmitigatedLossKwh = episodes.reduce(
      (sum, episode) => sum + episode.unmitigatedLossKwh,
      0,
    );

    return {
      runId,
      period: { from: query.from ?? null, to: query.to ?? null },
      reactorId: query.reactorId ?? null,
      holdMin: query.holdMin,
      measurementMode: 'ESTIMATED',
      savingRecordCount: episodes.length,
      totalUnmitigatedLossKwh: this.round(totalUnmitigatedLossKwh, 6),
      savingRatePct: this.round(
        totalUnmitigatedLossKwh > 0 ? (energySavedKwh / totalUnmitigatedLossKwh) * 100 : 0,
        2,
      ),
      ...convertEnergySaving(energySavedKwh, this.factors),
      calculationMethod: CALCULATION_METHOD,
      factorVersion: this.factors.version,
    };
  }

  async getReactorLosses(query: EsgQuery) {
    this.validateEsgQuery(query);
    const runId = await this.resolveRunId(query.runId);
    const episodes = await this.getEpisodeSavings(runId, query);
    const reactorIds = query.reactorId ? [query.reactorId] : await this.getReactorIds();

    const reactors = reactorIds.map((reactorId) => {
      const reactorEpisodes = episodes.filter((episode) => episode.reactorId === reactorId);
      const unmitigatedLossKwh = reactorEpisodes.reduce(
        (sum, episode) => sum + episode.unmitigatedLossKwh,
        0,
      );
      const actualLossUntilDetectionKwh = reactorEpisodes.reduce(
        (sum, episode) => sum + episode.actualLossUntilDetectionKwh,
        0,
      );
      const avoidableLossKwh = reactorEpisodes.reduce((sum, episode) => sum + episode.savedKwh, 0);

      return {
        reactorId,
        episodeCount: reactorEpisodes.length,
        unmitigatedLossKwh: this.round(unmitigatedLossKwh, 6),
        actualLossUntilDetectionKwh: this.round(actualLossUntilDetectionKwh, 6),
        avoidableLossKwh: this.round(avoidableLossKwh, 6),
        savingRatePct: this.round(
          unmitigatedLossKwh > 0 ? (avoidableLossKwh / unmitigatedLossKwh) * 100 : 0,
          2,
        ),
      };
    });

    const maxPlaybackMinute = Math.ceil(
      Math.max(...episodes.map((episode) => episode.modelDetectMinute), 0),
    );
    const playbackMinute = Math.min(query.playbackMinute ?? maxPlaybackMinute, maxPlaybackMinute);

    return {
      playbackMinute,
      maxPlaybackMinute,
      isPlaybackComplete: playbackMinute >= maxPlaybackMinute,
      totalUnmitigatedLossKwh: this.round(
        reactors.reduce((sum, reactor) => sum + reactor.unmitigatedLossKwh, 0),
        6,
      ),
      totalAvoidableLossKwh: this.round(
        reactors.reduce((sum, reactor) => sum + reactor.avoidableLossKwh, 0),
        6,
      ),
      reactors,
    };
  }

  async getMonthly(query: EsgQuery) {
    this.validateEsgQuery(query);
    const runId = await this.resolveRunId(query.runId);
    const episodes = await this.getEpisodeSavings(runId, query);
    const grouped = new Map<string, typeof episodes>();

    for (const episode of episodes) {
      const month = `${episode.detectTimestamp.toISOString().slice(0, 7)}-01`;
      grouped.set(month, [...(grouped.get(month) ?? []), episode]);
    }

    let cumulativeEnergySavedKwh = 0;
    return [...grouped.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([month, monthEpisodes]) => {
        const energySavedKwh = monthEpisodes.reduce((sum, episode) => sum + episode.savedKwh, 0);
        const totalUnmitigatedLossKwh = monthEpisodes.reduce(
          (sum, episode) => sum + episode.unmitigatedLossKwh,
          0,
        );
        cumulativeEnergySavedKwh += energySavedKwh;

        return {
          month,
          savingRecordCount: monthEpisodes.length,
          totalUnmitigatedLossKwh: this.round(totalUnmitigatedLossKwh, 6),
          savingRatePct: this.round(
            totalUnmitigatedLossKwh > 0 ? (energySavedKwh / totalUnmitigatedLossKwh) * 100 : 0,
            2,
          ),
          ...convertEnergySaving(energySavedKwh, this.factors),
          cumulativeEnergySavedKwh,
          cumulativeCo2ReducedKg: cumulativeEnergySavedKwh * this.factors.co2KgPerKwh,
          cumulativeTargetAchievementPct:
            this.factors.annualEnergyTargetKwh > 0
              ? (cumulativeEnergySavedKwh / this.factors.annualEnergyTargetKwh) * 100
              : null,
          calculationMethod: CALCULATION_METHOD,
          factorVersion: this.factors.version,
        };
      });
  }

  async getQuarterTargets(year: number) {
    this.validateTargetYear(year);
    const { rows } = await this.db.query<QuarterTargetRow>(`
      SELECT
        quarter,
        target_kwh AS "targetKwh",
        updated_at AS "updatedAt"
      FROM esg_quarter_targets
      WHERE year = $1
      ORDER BY quarter
    `, [year]);

    return {
      year,
      targets: rows.map((row) => ({
        quarter: row.quarter,
        targetKwh: Number(row.targetKwh),
        updatedAt: row.updatedAt,
      })),
    };
  }

  async saveQuarterTargets(
    year: number,
    targets: Array<{ quarter: number; targetKwh: number }>,
  ) {
    this.validateTargetYear(year);
    if (!Array.isArray(targets)) {
      throw new BadRequestException('targets must be an array.');
    }

    const normalizedTargets = targets.map((target) => ({
      quarter: Number(target?.quarter),
      targetKwh: Number(target?.targetKwh),
    }));
    const quarters = normalizedTargets.map((target) => target.quarter);

    if (
      normalizedTargets.some((target) => (
        !Number.isInteger(target.quarter)
        || target.quarter < 1
        || target.quarter > 4
        || !Number.isFinite(target.targetKwh)
        || target.targetKwh <= 0
      ))
    ) {
      throw new BadRequestException('Each target requires quarter 1-4 and targetKwh greater than 0.');
    }
    if (new Set(quarters).size !== quarters.length) {
      throw new BadRequestException('Each quarter can only be included once.');
    }

    await this.db.query(`
      WITH input AS (
        SELECT quarter, target_kwh
        FROM UNNEST($2::INTEGER[], $3::NUMERIC[]) AS value(quarter, target_kwh)
      ),
      deleted AS (
        DELETE FROM esg_quarter_targets existing
        WHERE existing.year = $1
          AND NOT EXISTS (
            SELECT 1 FROM input WHERE input.quarter = existing.quarter
          )
      )
      INSERT INTO esg_quarter_targets (year, quarter, target_kwh, updated_at)
      SELECT $1, quarter, target_kwh, NOW()
      FROM input
      ON CONFLICT (year, quarter) DO UPDATE
      SET target_kwh = EXCLUDED.target_kwh,
          updated_at = NOW()
    `, [year, quarters, normalizedTargets.map((target) => target.targetKwh)]);

    return this.getQuarterTargets(year);
  }

  async getTrainingEstimate(from: string, to: string, assumedDetectionMin = 15) {
    const query: EsgQuery = { from, to, holdMin: 0 };
    this.validateEsgQuery(query);
    if (!from || !to) {
      throw new BadRequestException('from and to are required.');
    }
    if (!Number.isInteger(assumedDetectionMin) || assumedDetectionMin < 0) {
      throw new BadRequestException('assumedDetectionMin must be a non-negative integer.');
    }

    const { rows } = await this.db.query<TrainingEpisodeRow>(
      `
        WITH readings_with_previous AS (
          SELECT
            timestamp,
            reactor_id,
            COALESCE(operating_regime, LEFT(reactor_id, 1)) AS operating_regime,
            fault_type,
            LAG(timestamp) OVER (PARTITION BY reactor_id ORDER BY timestamp) AS previous_timestamp,
            LAG(fault_type) OVER (PARTITION BY reactor_id ORDER BY timestamp) AS previous_fault_type
          FROM economic_power_readings
          WHERE timestamp >= ($1::date - INTERVAL '1 minute')
            AND timestamp < ($2::date + INTERVAL '1 day')
        ),
        fault_starts AS (
          SELECT
            timestamp AS onset_timestamp,
            reactor_id,
            operating_regime,
            fault_type
          FROM readings_with_previous
          WHERE timestamp >= $1::date
            AND timestamp < ($2::date + INTERVAL '1 day')
            AND fault_type <> 0
            AND (
              previous_fault_type IS DISTINCT FROM fault_type
              OR previous_timestamp IS DISTINCT FROM timestamp - INTERVAL '1 minute'
            )
        )
        SELECT
          start.reactor_id AS "reactorId",
          start.operating_regime AS "operatingRegime",
          start.fault_type::int AS fault,
          start.onset_timestamp AS "onsetTimestamp",
          COALESCE(SUM(GREATEST(COALESCE(reading.wasted_power_kw, 0), 0)), 0)::float / 60.0
            AS "actualLossUntilDetectionKwh"
        FROM fault_starts start
        LEFT JOIN economic_power_readings reading
          ON reading.reactor_id = start.reactor_id
         AND reading.timestamp >= start.onset_timestamp
         AND reading.timestamp < start.onset_timestamp + ($3::int * INTERVAL '1 minute')
        GROUP BY
          start.reactor_id,
          start.operating_regime,
          start.fault_type,
          start.onset_timestamp
        ORDER BY start.onset_timestamp
      `,
      [from, to, assumedDetectionMin],
    );

    const episodes = rows.map((row) => {
      const regime = this.normalizeRegime(row.operatingRegime);
      const unmitigatedLossKwh = UNMITIGATED_LOSS_KWH[regime][row.fault];
      const actualLossUntilDetectionKwh = Number(row.actualLossUntilDetectionKwh);
      return {
        date: new Date(row.onsetTimestamp).toISOString().slice(0, 10),
        savedKwh: Math.max(unmitigatedLossKwh - actualLossUntilDetectionKwh, 0),
      };
    });
    const dailyTotals = new Map<string, number>();
    for (const episode of episodes) {
      dailyTotals.set(episode.date, (dailyTotals.get(episode.date) ?? 0) + episode.savedKwh);
    }
    let cumulativeEnergySavedKwh = 0;
    const dailySavings = [...dailyTotals.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([date, energySavedKwh]) => {
        cumulativeEnergySavedKwh += energySavedKwh;
        return {
          date,
          energySavedKwh: this.round(energySavedKwh, 6),
          cumulativeEnergySavedKwh: this.round(cumulativeEnergySavedKwh, 6),
        };
      });
    const energySavedKwh = episodes.reduce((sum, episode) => sum + episode.savedKwh, 0);
    const totalUnmitigatedLossKwh = rows.reduce((sum, row) => {
      const regime = this.normalizeRegime(row.operatingRegime);
      return sum + UNMITIGATED_LOSS_KWH[regime][row.fault];
    }, 0);

    return {
      period: { from, to },
      measurementMode: 'TRAINING_DATA_ESTIMATE',
      assumedDetectionMin,
      savingRecordCount: episodes.length,
      totalUnmitigatedLossKwh: this.round(totalUnmitigatedLossKwh, 6),
      savingRatePct: this.round(
        totalUnmitigatedLossKwh > 0 ? (energySavedKwh / totalUnmitigatedLossKwh) * 100 : 0,
        2,
      ),
      ...convertEnergySaving(energySavedKwh, this.factors),
      dailySavings,
      calculationMethod: CALCULATION_METHOD,
      factorVersion: this.factors.version,
    };
  }

  private async getEpisodeSavings(runId: string, query: EsgQuery) {
    const conditions = ['er.run_id = $1', 'er.hold_min = $2', 'er.correct_delay_min IS NOT NULL'];
    const params: unknown[] = [runId, query.holdMin];

    if (query.from) {
      params.push(query.from);
      conditions.push(`fe.event_time >= $${params.length}::date`);
    }
    if (query.to) {
      params.push(query.to);
      conditions.push(`fe.event_time < ($${params.length}::date + INTERVAL '1 day')`);
    }
    if (query.reactorId) {
      params.push(query.reactorId);
      conditions.push(`er.reactor_id = $${params.length}`);
    }
    params.push(query.playbackMinute ?? null);
    const playbackMinuteParam = `$${params.length}`;

    const { rows } = await this.db.query<EpisodeLossRow>(
      `
        WITH correct_detections AS (
          SELECT DISTINCT ON (er.episode_id)
            er.episode_id,
            er.reactor_id,
            er.fault AS predicted_fault,
            er.correct_delay_min,
            fe.event_time AS detect_timestamp,
            fe.event_time - (er.correct_delay_min * INTERVAL '1 minute') AS onset_timestamp
          FROM episode_results er
          INNER JOIN fault_events fe
            ON fe.run_id = er.run_id
           AND fe.hold_min = er.hold_min
           AND fe.episode_id = er.episode_id
           AND fe.reactor_id = er.reactor_id
           AND fe.predicted_fault = er.fault
          WHERE ${conditions.join(' AND ')}
          ORDER BY er.episode_id, fe.event_time
        )
        , calculation_windows AS (
          SELECT
            d.*,
            CASE
              WHEN ${playbackMinuteParam}::double precision IS NULL THEN d.detect_timestamp
              ELSE LEAST(
                d.detect_timestamp,
                d.onset_timestamp + (${playbackMinuteParam}::double precision * INTERVAL '1 minute')
              )
            END AS calculation_timestamp
          FROM correct_detections d
        )
        SELECT
          d.episode_id AS "episodeId",
          d.reactor_id AS "reactorId",
          d.predicted_fault::int AS "predictedFault",
          d.onset_timestamp AS "onsetTimestamp",
          d.calculation_timestamp AS "detectTimestamp",
          d.correct_delay_min::float AS "detectMinute",
          COALESCE(detection.operating_regime, LEFT(d.reactor_id, 1)) AS "operatingRegime",
          detection.fault_type::int AS "actualFaultAtDetection",
          GREATEST(COALESCE(detection.wasted_power_kw, 0), 0)::float AS "wastedPowerKwAtDetection",
          COUNT(loss_reading.timestamp)::int AS "integratedMinutes",
          COALESCE(SUM(
            GREATEST(COALESCE(loss_reading.wasted_power_kw, 0), 0)
          ), 0)::float / 60.0 AS "actualLossUntilDetectionKwh"
        FROM calculation_windows d
        INNER JOIN economic_power_readings detection
          ON detection.reactor_id = d.reactor_id
         AND detection.timestamp = d.calculation_timestamp
        LEFT JOIN economic_power_readings loss_reading
          ON loss_reading.reactor_id = d.reactor_id
         AND loss_reading.timestamp >= d.onset_timestamp
         AND loss_reading.timestamp < d.calculation_timestamp
        GROUP BY
          d.episode_id,
          d.reactor_id,
          d.predicted_fault,
          d.onset_timestamp,
          d.detect_timestamp,
          d.calculation_timestamp,
          d.correct_delay_min,
          detection.operating_regime,
          detection.fault_type,
          detection.wasted_power_kw
        ORDER BY d.detect_timestamp
      `,
      params,
    );

    return rows.map((row) => ({
      episodeId: row.episodeId,
      modelDetectMinute: Number(row.detectMinute),
      ...this.toPowerSavingResult({
        reactorId: row.reactorId,
        regime: this.normalizeRegime(row.operatingRegime),
        fault: row.predictedFault,
        actualFaultAtDetection: row.actualFaultAtDetection,
        onset: new Date(row.onsetTimestamp),
        detect: new Date(row.detectTimestamp),
        integratedMinutes: row.integratedMinutes,
        wastedPowerKwAtDetection: Number(row.wastedPowerKwAtDetection),
        actualLossUntilDetectionKwh: Number(row.actualLossUntilDetectionKwh),
      }),
    }));
  }

  private async getReactorIds() {
    const { rows } = await this.db.query<{ reactorId: string }>(`
      SELECT DISTINCT reactor_id AS "reactorId"
      FROM economic_power_readings
      ORDER BY reactor_id
    `);

    return rows.map((row) => row.reactorId);
  }

  private toPowerSavingResult(input: {
    reactorId: string;
    regime: Regime;
    fault: number;
    actualFaultAtDetection: number;
    onset: Date;
    detect: Date;
    integratedMinutes: number;
    wastedPowerKwAtDetection: number;
    actualLossUntilDetectionKwh: number;
  }) {
    const unmitigatedLossKwh = UNMITIGATED_LOSS_KWH[input.regime][input.fault];
    const savedKwh = Math.max(unmitigatedLossKwh - input.actualLossUntilDetectionKwh, 0);

    return {
      reactorId: input.reactorId,
      operatingRegime: input.regime,
      predictedFault: input.fault,
      actualFaultAtDetection: input.actualFaultAtDetection,
      faultMatch: input.actualFaultAtDetection === input.fault,
      onsetTimestamp: input.onset,
      detectTimestamp: input.detect,
      detectMinute: this.round((input.detect.getTime() - input.onset.getTime()) / 60_000, 2),
      wastedPowerKwAtDetection: this.round(input.wastedPowerKwAtDetection, 6),
      integratedMinutes: input.integratedMinutes,
      unmitigatedLossKwh: this.round(unmitigatedLossKwh, 6),
      actualLossUntilDetectionKwh: this.round(input.actualLossUntilDetectionKwh, 6),
      savedKwh: this.round(savedKwh, 6),
      savingRatePct: this.round(unmitigatedLossKwh > 0 ? (savedKwh / unmitigatedLossKwh) * 100 : 0, 2),
      calculationMethod: CALCULATION_METHOD,
    };
  }

  private normalizeFault(rawFault: string) {
    if (!rawFault?.trim()) {
      throw new BadRequestException('predictedFault is required.');
    }
    const normalized = rawFault.trim().toUpperCase().replace(/^F/, '');
    const fault = Number(normalized);
    if (!Number.isInteger(fault) || ![1, 2, 3, 4].includes(fault)) {
      throw new BadRequestException(`Invalid predictedFault: ${rawFault}`);
    }
    return fault;
  }

  private validateTargetYear(year: number) {
    if (!Number.isInteger(year) || year < 2000 || year > 9999) {
      throw new BadRequestException('year must be an integer between 2000 and 9999.');
    }
  }

  private normalizeRegime(rawRegime: string): Regime {
    const regime = rawRegime.trim().toUpperCase();
    if (regime !== 'A' && regime !== 'B') {
      throw new BadRequestException(`Invalid operating regime: ${rawRegime}`);
    }
    return regime;
  }

  private resolveDetectionTimestamp(onset: Date, query: PowerSavingQuery) {
    if (query.detectTimestamp) {
      return this.parseTimestamp(query.detectTimestamp, 'detectTimestamp');
    }
    if (query.detectMinute === undefined || !Number.isFinite(query.detectMinute) || query.detectMinute < 0) {
      throw new BadRequestException('detectTimestamp or a non-negative detectMinute is required.');
    }
    return new Date(onset.getTime() + query.detectMinute * 60_000);
  }

  private parseTimestamp(raw: string, fieldName: string) {
    if (!raw?.trim()) {
      throw new BadRequestException(`${fieldName} is required.`);
    }
    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
    const normalized = hasTimezone ? raw : `${raw.replace(' ', 'T')}Z`;
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) {
      throw new BadRequestException(`${fieldName} must be a valid ISO datetime.`);
    }
    return parsed;
  }

  private async resolveRunId(runId?: string) {
    if (runId) {
      return runId;
    }
    const { rows } = await this.db.query<{ id: string }>(`
      SELECT id FROM model_runs ORDER BY imported_at DESC LIMIT 1
    `);
    if (!rows[0]) {
      throw new NotFoundException('No imported model run found.');
    }
    return rows[0].id;
  }

  private validateEsgQuery(query: EsgQuery) {
    if (!Number.isInteger(query.holdMin) || query.holdMin < 0) {
      throw new BadRequestException('holdMin must be a non-negative integer.');
    }
    if (
      query.playbackMinute !== undefined
      && (!Number.isInteger(query.playbackMinute) || query.playbackMinute < 0)
    ) {
      throw new BadRequestException('playbackMinute must be a non-negative integer.');
    }
    for (const [name, value] of [
      ['from', query.from],
      ['to', query.to],
    ] as const) {
      if (value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        throw new BadRequestException(`${name} must use YYYY-MM-DD format.`);
      }
    }
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

  private round(value: number, digits: number) {
    const scale = 10 ** digits;
    return Math.round((value + Number.EPSILON) * scale) / scale;
  }
}
