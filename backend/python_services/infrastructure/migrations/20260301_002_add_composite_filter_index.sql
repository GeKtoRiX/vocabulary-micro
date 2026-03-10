CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_category_confidence
ON lexicon_entries(status, category COLLATE NOCASE, confidence);
