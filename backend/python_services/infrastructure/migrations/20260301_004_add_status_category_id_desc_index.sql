CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_category_id_desc
ON lexicon_entries(status, category COLLATE NOCASE, id DESC);
