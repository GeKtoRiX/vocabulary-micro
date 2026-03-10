CREATE TABLE IF NOT EXISTS lexicon_entries (
  id BIGSERIAL PRIMARY KEY,
  category TEXT NOT NULL,
  value TEXT NOT NULL,
  normalized TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  confidence DOUBLE PRECISION NULL,
  first_seen_at TEXT NULL,
  request_id TEXT NULL,
  example_usage TEXT NULL,
  status TEXT NOT NULL DEFAULT 'approved',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TEXT NULL,
  reviewed_by TEXT NULL,
  review_note TEXT NULL,
  UNIQUE(category, normalized)
);

CREATE TABLE IF NOT EXISTS lexicon_categories (
  name TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lexicon_meta (
  id INTEGER PRIMARY KEY,
  lexicon_version BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO lexicon_meta(id, lexicon_version, updated_at)
VALUES (1, 0, CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status ON lexicon_entries(status);
CREATE INDEX IF NOT EXISTS idx_lexicon_entries_normalized ON lexicon_entries(normalized);
CREATE INDEX IF NOT EXISTS idx_lexicon_entries_confidence ON lexicon_entries(confidence);

INSERT INTO lexicon_categories(name)
SELECT DISTINCT category
FROM lexicon_entries
WHERE TRIM(category) <> ''
ON CONFLICT(name) DO NOTHING;

CREATE TABLE IF NOT EXISTS mwe_expressions (
  id BIGSERIAL PRIMARY KEY,
  canonical_form TEXT NOT NULL UNIQUE,
  expression_type TEXT NOT NULL CHECK(expression_type IN ('phrasal_verb', 'idiom')),
  base_lemma TEXT NOT NULL DEFAULT '',
  particle TEXT NOT NULL DEFAULT '',
  is_separable INTEGER NOT NULL DEFAULT 0,
  max_gap_tokens INTEGER NOT NULL DEFAULT 4,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mwe_senses (
  id BIGSERIAL PRIMARY KEY,
  expression_id BIGINT NOT NULL REFERENCES mwe_expressions(id) ON DELETE CASCADE,
  sense_key TEXT NOT NULL,
  gloss TEXT NOT NULL,
  usage_label TEXT NOT NULL CHECK(usage_label IN ('literal', 'idiomatic')),
  example TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(expression_id, sense_key)
);

CREATE TABLE IF NOT EXISTS mwe_meta (
  id INTEGER PRIMARY KEY,
  mwe_version BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO mwe_meta(id, mwe_version, updated_at)
VALUES (1, 0, CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_mwe_senses_expression_id ON mwe_senses(expression_id);
CREATE INDEX IF NOT EXISTS idx_mwe_expressions_type ON mwe_expressions(expression_type);
