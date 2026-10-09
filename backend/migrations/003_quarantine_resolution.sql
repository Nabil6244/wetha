ALTER TABLE rejected_evidence ADD COLUMN resolved_at TEXT;
CREATE INDEX rejected_unresolved ON rejected_evidence(feed_id, resolved_at);
