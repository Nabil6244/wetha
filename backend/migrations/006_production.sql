CREATE TABLE production_media (
    id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL UNIQUE,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE production_timelines (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES visual_plans(id),
    document TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE production_renders (
    id TEXT PRIMARY KEY,
    timeline_id TEXT NOT NULL REFERENCES production_timelines(id),
    status TEXT NOT NULL,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
