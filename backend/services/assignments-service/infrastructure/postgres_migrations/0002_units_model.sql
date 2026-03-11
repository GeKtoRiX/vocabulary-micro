DROP TABLE IF EXISTS assignment_audio;
DROP TABLE IF EXISTS assignments;

CREATE TABLE IF NOT EXISTS units (
  id SERIAL PRIMARY KEY,
  unit_code TEXT NOT NULL UNIQUE,
  unit_number INTEGER NOT NULL UNIQUE,
  subunit_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_units_unit_number
ON units(unit_number DESC);

CREATE INDEX IF NOT EXISTS idx_units_created_at
ON units(created_at DESC);

CREATE TABLE IF NOT EXISTS unit_subunits (
  id SERIAL PRIMARY KEY,
  unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
  subunit_code TEXT NOT NULL,
  position INTEGER NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_unit_subunits_unit_position
ON unit_subunits(unit_id, position);

CREATE INDEX IF NOT EXISTS idx_unit_subunits_unit_id
ON unit_subunits(unit_id, position ASC);
