CREATE TABLE feeds (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    last_attempt_at TEXT,
    last_success_at TEXT,
    next_poll_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'never_collected',
    collected_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0
);
INSERT INTO feeds(id, url) VALUES
('nws', 'https://api.weather.gov/alerts/active'),
('nhc', 'https://www.nhc.noaa.gov/index-at.xml');
CREATE TABLE http_cache (
    url TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    body TEXT NOT NULL,
    checksum TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE TABLE feed_members (
    feed_id TEXT NOT NULL REFERENCES feeds(id),
    advisory_id TEXT NOT NULL REFERENCES advisories(id),
    PRIMARY KEY(feed_id, advisory_id)
);
CREATE TABLE rejected_evidence (
    id TEXT PRIMARY KEY,
    feed_id TEXT NOT NULL REFERENCES feeds(id),
    source_identifier TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE news_events (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
