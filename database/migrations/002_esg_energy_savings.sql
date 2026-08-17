-- ESG energy savings calculated by the offline Python batch.
-- This table stores auditable calculation results; NestJS only aggregates and converts them.

CREATE TABLE IF NOT EXISTS esg_energy_savings (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
  timestamp TIMESTAMPTZ NOT NULL,
  reactor_id TEXT NOT NULL,
  fault_type INTEGER NOT NULL CHECK (fault_type BETWEEN 1 AND 4),
  episode_id INTEGER,
  baseline_sty DOUBLE PRECISION,
  actual_sty DOUBLE PRECISION,
  baseline_power_kw DOUBLE PRECISION,
  actual_power_kw DOUBLE PRECISION,
  energy_saved_kwh DOUBLE PRECISION NOT NULL CHECK (energy_saved_kwh >= 0),
  calculation_method TEXT NOT NULL,
  calculation_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, reactor_id, timestamp, fault_type)
);

CREATE INDEX IF NOT EXISTS idx_esg_energy_savings_run_time
  ON esg_energy_savings (run_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_esg_energy_savings_run_reactor_time
  ON esg_energy_savings (run_id, reactor_id, timestamp);
