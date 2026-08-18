-- Green-Pulse backend schema
-- 이 DB는 모델을 실시간으로 돌리는 용도가 아니라,
-- Python 배치 파이프라인이 만든 결과를 저장하고 프론트가 빠르게 조회하도록 만드는 용도입니다.

CREATE TABLE IF NOT EXISTS model_runs (
  id TEXT PRIMARY KEY,
  workspace_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'imported',
  data_start_at TIMESTAMPTZ,
  data_end_at TIMESTAMPTZ,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS reactor_readings (
  id BIGSERIAL PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL,
  operating_regime TEXT,
  reactor_id TEXT NOT NULL,
  ambient_temp_effect DOUBLE PRECISION,
  reactor_temp DOUBLE PRECISION,
  reactor_pressure DOUBLE PRECISION,
  feed_flow_rate DOUBLE PRECISION,
  coolant_flow_rate DOUBLE PRECISION,
  agitator_speed_rpm DOUBLE PRECISION,
  reaction_rate DOUBLE PRECISION,
  conversion_rate DOUBLE PRECISION,
  selectivity DOUBLE PRECISION,
  yield_pct DOUBLE PRECISION,
  vibration_rms DOUBLE PRECISION,
  motor_current DOUBLE PRECISION,
  power_consumption_kw DOUBLE PRECISION,
  temp_setpoint DOUBLE PRECISION,
  pressure_setpoint DOUBLE PRECISION,
  fault_type INTEGER NOT NULL,
  efficiency_loss_pct DOUBLE PRECISION,
  time_to_fault_min DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (reactor_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_reactor_readings_timestamp ON reactor_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_reactor_readings_reactor_time ON reactor_readings (reactor_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_reactor_readings_fault_time ON reactor_readings (fault_type, timestamp);

-- ESG 전력 계산 전용 데이터입니다.
-- economic_power_calculation_5cols.csv의 5개 컬럼만 그대로 저장합니다.
CREATE TABLE IF NOT EXISTS economic_power_readings (
  timestamp TIMESTAMPTZ NOT NULL,
  operating_regime TEXT NOT NULL,
  reactor_id TEXT NOT NULL,
  fault_type INTEGER NOT NULL,
  wasted_power_kw DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (reactor_id, timestamp),
  CHECK (operating_regime IN ('A', 'B')),
  CHECK (fault_type BETWEEN 0 AND 4),
  CHECK (wasted_power_kw >= 0)
);

CREATE INDEX IF NOT EXISTS idx_economic_power_timestamp
  ON economic_power_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_economic_power_fault_time
  ON economic_power_readings (fault_type, timestamp);

CREATE TABLE IF NOT EXISTS fault_events (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
  event_index INTEGER NOT NULL,
  event_time TIMESTAMPTZ,
  reactor_id TEXT NOT NULL,
  predicted_fault INTEGER NOT NULL,
  true_fault INTEGER,
  specialist TEXT NOT NULL,
  score DOUBLE PRECISION,
  hold_min INTEGER NOT NULL DEFAULT 0,
  episode_id INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fault_events_run_hold ON fault_events (run_id, hold_min);
CREATE INDEX IF NOT EXISTS idx_fault_events_time ON fault_events (event_time);
CREATE INDEX IF NOT EXISTS idx_fault_events_reactor_time ON fault_events (reactor_id, event_time);

CREATE TABLE IF NOT EXISTS episode_results (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
  hold_min INTEGER NOT NULL DEFAULT 0,
  episode_id INTEGER NOT NULL,
  fault INTEGER NOT NULL,
  reactor_id TEXT NOT NULL,
  correct_delay_min DOUBLE PRECISION,
  wrong_delay_min DOUBLE PRECISION,
  wrong_before_correct BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, hold_min, episode_id)
);

CREATE INDEX IF NOT EXISTS idx_episode_results_run_hold ON episode_results (run_id, hold_min);

CREATE TABLE IF NOT EXISTS run_metrics (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
  metric_group TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value DOUBLE PRECISION,
  metric_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, metric_group, metric_name)
);

CREATE TABLE IF NOT EXISTS monthly_summaries (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
  month DATE NOT NULL,
  reactor_id TEXT,
  reading_count INTEGER NOT NULL,
  fault_reading_count INTEGER NOT NULL,
  normal_reading_count INTEGER NOT NULL,
  predicted_event_count INTEGER NOT NULL,
  avg_reactor_temp DOUBLE PRECISION,
  avg_pressure DOUBLE PRECISION,
  avg_efficiency_loss_pct DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (run_id, month, reactor_id)
);

CREATE INDEX IF NOT EXISTS idx_monthly_summaries_run_month ON monthly_summaries (run_id, month);
