CREATE TABLE IF NOT EXISTS esg_quarter_targets (
  year INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 9999),
  quarter INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  target_kwh NUMERIC(14, 3) NOT NULL CHECK (target_kwh > 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (year, quarter)
);

