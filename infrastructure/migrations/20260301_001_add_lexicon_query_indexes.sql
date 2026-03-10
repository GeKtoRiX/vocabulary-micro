CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status
ON lexicon_entries(status);

CREATE INDEX IF NOT EXISTS idx_lexicon_entries_category
ON lexicon_entries(category);

CREATE INDEX IF NOT EXISTS idx_lexicon_entries_confidence
ON lexicon_entries(confidence);
