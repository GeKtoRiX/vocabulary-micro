CREATE TABLE IF NOT EXISTS assignments (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  content_original TEXT NOT NULL,
  content_completed TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  lexicon_coverage_percent DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assignments_created_at
ON assignments(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_assignments_status
ON assignments(status);

CREATE TABLE IF NOT EXISTS assignment_audio (
  id SERIAL PRIMARY KEY,
  assignment_id INTEGER NOT NULL,
  audio_path TEXT NOT NULL,
  audio_format TEXT NOT NULL DEFAULT 'wav',
  voice TEXT NOT NULL DEFAULT 'af_heart',
  style_preset TEXT NOT NULL DEFAULT 'neutral',
  duration_sec DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  sample_rate INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assignment_audio_assignment_id_created
ON assignment_audio(assignment_id, created_at DESC);
