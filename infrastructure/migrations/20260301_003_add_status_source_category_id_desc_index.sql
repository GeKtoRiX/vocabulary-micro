CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_source_category_id_desc
ON lexicon_entries(status, source, category COLLATE NOCASE, id DESC);
