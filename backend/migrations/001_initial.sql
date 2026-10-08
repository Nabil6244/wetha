CREATE TABLE IF NOT EXISTS advisories (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    event_key TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    checksum TEXT NOT NULL,
    document TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS advisory_event_time ON advisories(event_key, issued_at);
CREATE TABLE IF NOT EXISTS scripts (
    id TEXT PRIMARY KEY,
    advisory_id TEXT NOT NULL REFERENCES advisories(id),
    document TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_profiles (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL
);
INSERT OR IGNORE INTO channel_profiles(id, document) VALUES
('us-extreme', '{"id":"us-extreme","name":"US Extreme Weather","region":"United States","language":"en-US","schedule_minutes":60,"auto_broadcast":false}');
