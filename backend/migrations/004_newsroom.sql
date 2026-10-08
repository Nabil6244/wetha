CREATE TABLE newsroom_runs (
    id TEXT PRIMARY KEY,
    advisory_id TEXT NOT NULL REFERENCES advisories(id),
    engine TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    script_id TEXT REFERENCES scripts(id),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE agent_steps (
    run_id TEXT NOT NULL REFERENCES newsroom_runs(id),
    sequence INTEGER NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
    input_document TEXT NOT NULL,
    output_document TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY(run_id, sequence)
);
CREATE TABLE script_versions (
    script_id TEXT NOT NULL REFERENCES scripts(id),
    revision INTEGER NOT NULL,
    document TEXT NOT NULL,
    editor TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(script_id, revision)
);
INSERT INTO script_versions SELECT id, 1, document, 'Legacy writer', 'Preserved pre-Phase 3 draft', created_at FROM scripts;
CREATE TABLE editorial_reviews (
    id TEXT PRIMARY KEY,
    script_id TEXT NOT NULL REFERENCES scripts(id),
    revision INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    evidence_document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(script_id, revision) REFERENCES script_versions(script_id, revision)
);
