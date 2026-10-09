CREATE TABLE visual_assets (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source_url TEXT NOT NULL UNIQUE,
    observed_at TEXT NOT NULL,
    content_type TEXT NOT NULL,
    body BLOB NOT NULL,
    checksum TEXT NOT NULL,
    document TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE visual_sources (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'not_collected',
    checked_at TEXT,
    last_error TEXT
);
INSERT INTO visual_sources(id) VALUES ('goes'), ('radar'), ('forecast_cone');
CREATE TABLE visual_plans (
    id TEXT PRIMARY KEY,
    script_id TEXT NOT NULL,
    script_revision INTEGER NOT NULL,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(script_id, script_revision) REFERENCES script_versions(script_id, revision)
);
