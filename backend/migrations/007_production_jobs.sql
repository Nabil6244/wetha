CREATE TABLE production_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
