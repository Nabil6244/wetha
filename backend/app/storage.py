import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .contracts import Advisory


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RevisionConflict(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            migrations = Path(__file__).resolve().parents[1] / "migrations"
            for migration in sorted(migrations.glob("*.sql")):
                if not conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (migration.name,)).fetchone():
                    # executescript commits its own transaction; include the migration marker atomically.
                    script = "BEGIN IMMEDIATE;\n" + migration.read_text() + "\nINSERT INTO schema_migrations VALUES ('" + migration.name + "', '" + now() + "');\nCOMMIT;"
                    conn.executescript(script)
            conn.execute("UPDATE jobs SET status='failed', detail='Interrupted by backend restart', updated_at=? WHERE status='running'", (now(),))
            conn.execute("UPDATE feeds SET status='failed', last_error='Collection interrupted by backend restart', consecutive_failures=consecutive_failures+1 WHERE status='collecting'")
            conn.execute("UPDATE newsroom_runs SET status='failed', error='Interrupted by backend restart', updated_at=? WHERE status='running'", (now(),))
            conn.execute("UPDATE agent_steps SET status='failed', error='Interrupted by backend restart', finished_at=? WHERE status='running'", (now(),))

    def save_advisory(self, item: Advisory) -> bool:
        with self.connection() as conn:
            return self._insert_advisory(conn, item)

    @staticmethod
    def _insert_advisory(conn, item):
        existing = conn.execute("SELECT checksum, document FROM advisories WHERE id=?", (item.id,)).fetchone()
        if existing:
            if existing["checksum"] != item.checksum:
                raise ValueError("This advisory ID already exists with different content; evidence is immutable.")
            old = Advisory.model_validate_json(existing["document"])
            if item.provenance == "official_fetch" and old.provenance == "manual_import":
                conn.execute("UPDATE advisories SET document=? WHERE id=?", (item.model_dump_json(), item.id))
            return False
        conn.execute("INSERT INTO advisories VALUES (?, ?, ?, ?, ?, ?, ?)", (item.id, item.provider, item.event_key, item.issued_at.isoformat(), item.checksum, item.model_dump_json(), now()))
        return True

    def advisories(self) -> list[Advisory]:
        with self.connection() as conn:
            return [Advisory.model_validate_json(r["document"]) for r in conn.execute("SELECT document FROM advisories ORDER BY issued_at DESC, id")]

    def advisory(self, identity: str) -> Advisory:
        with self.connection() as conn:
            row = conn.execute("SELECT document FROM advisories WHERE id=?", (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            return Advisory.model_validate_json(row["document"])

    def previous(self, item: Advisory) -> Advisory | None:
        from .intelligence import IntelligenceDesk
        return IntelligenceDesk(self.advisories()).previous(item)

    def save_script(self, document: dict):
        with self.connection() as conn:
            conn.execute("INSERT INTO scripts VALUES (?, ?, ?, ?)", (document["id"], document["advisory_id"], json.dumps(document), now()))
            conn.execute('INSERT INTO script_versions VALUES (?, 1, ?, ?, ?, ?)', (document['id'], json.dumps(document), 'Grounded writer', 'Initial source-backed draft', now()))

    def scripts(self) -> list[dict]:
        with self.connection() as conn:
            return [json.loads(r["document"]) for r in conn.execute("SELECT document FROM scripts ORDER BY created_at DESC, id")]

    def script(self, identity: str, revision: int | None = None) -> dict:
        with self.connection() as conn:
            if revision is None:
                row = conn.execute('SELECT document FROM scripts WHERE id=?', (identity,)).fetchone()
            else:
                row = conn.execute('SELECT document FROM script_versions WHERE script_id=? AND revision=?', (identity, revision)).fetchone()
            if not row:
                raise KeyError(identity)
            return json.loads(row['document'])

    def versions(self, identity: str) -> list[dict]:
        self.script(identity)
        with self.connection() as conn:
            return [dict(row) for row in conn.execute('SELECT revision, editor, note, created_at FROM script_versions WHERE script_id=? ORDER BY revision DESC', (identity,))]

    def revise(self, identity: str, expected: int, editor: str, note: str, build) -> dict:
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT document FROM scripts WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            current = json.loads(row['document'])
            if current.get('revision', 1) != expected:
                raise RevisionConflict('This draft changed. Reload the latest revision before saving.')
            document = build(current)
            document.update(revision=expected + 1, editor=editor, revision_note=note, updated_at=now())
            conn.execute('INSERT INTO script_versions VALUES (?, ?, ?, ?, ?, ?)', (identity, expected+1, json.dumps(document), editor, note, now()))
            conn.execute('UPDATE scripts SET document=? WHERE id=?', (json.dumps(document), identity))
            return document

    def reviews(self, identity: str) -> list[dict]:
        self.script(identity)
        with self.connection() as conn:
            rows = [dict(row) for row in conn.execute('SELECT * FROM editorial_reviews WHERE script_id=? ORDER BY created_at DESC, id', (identity,))]
        for row in rows:
            row['evidence'] = json.loads(row.pop('evidence_document'))
        return rows

    def review_script(self, identity: str, reviewer: str, expected: int | None = None, note: str = '', validate=None):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT document FROM scripts WHERE id=?", (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            document = json.loads(row["document"])
            revision = document.get('revision', 1)
            if expected != revision and not (expected is None and revision == 1):
                raise RevisionConflict('Review must name the latest revision. Reload this draft before approving.')
            if validate:
                document = validate(document)
            document.update(status="reviewed", reviewer=reviewer, reviewed_at=now())
            for check in document["qc"]:
                if check["check"] == "Human editorial review":
                    check["passed"] = True
            conn.execute("UPDATE scripts SET document=? WHERE id=?", (json.dumps(document), identity))
            conn.execute('INSERT INTO editorial_reviews VALUES (?, ?, ?, ?, ?, ?, ?)', (str(uuid4()), identity, revision, reviewer, note, json.dumps(document.get('evidence_manifest', [])), now()))
            return document

    def start_run(self, advisory_id: str, engine: str) -> str:
        identity = str(uuid4())
        with self.connection() as conn:
            conn.execute("INSERT INTO newsroom_runs VALUES (?, ?, ?, 'running', NULL, NULL, ?, ?)", (identity, advisory_id, engine, now(), now()))
        return identity

    def start_step(self, identity: str, sequence: int, agent: str, input_document: dict):
        with self.connection() as conn:
            conn.execute("INSERT INTO agent_steps VALUES (?, ?, ?, 'running', ?, NULL, NULL, ?, NULL)", (identity, sequence, agent, json.dumps(input_document), now()))

    def finish_step(self, identity: str, sequence: int, output: dict | None = None, error: str | None = None):
        with self.connection() as conn:
            conn.execute('UPDATE agent_steps SET status=?, output_document=?, error=?, finished_at=? WHERE run_id=? AND sequence=?', ('failed' if error else 'succeeded', json.dumps(output) if output is not None else None, error, now(), identity, sequence))

    def finish_run(self, identity: str, document: dict | None = None, error: str | None = None):
        with self.connection() as conn:
            if document:
                conn.execute('INSERT INTO scripts VALUES (?, ?, ?, ?)', (document['id'], document['advisory_id'], json.dumps(document), now()))
                conn.execute('INSERT INTO script_versions VALUES (?, 1, ?, ?, ?, ?)', (document['id'], json.dumps(document), 'Grounded writer', 'Initial newsroom draft', now()))
            conn.execute('UPDATE newsroom_runs SET status=?, script_id=?, error=?, updated_at=? WHERE id=?', ('failed' if error else 'succeeded', document['id'] if document else None, error, now(), identity))

    def runs(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM newsroom_runs ORDER BY created_at DESC, id LIMIT 30')]

    def run(self, identity: str) -> dict:
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM newsroom_runs WHERE id=?', (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            result = dict(row)
            result['steps'] = [dict(row) for row in conn.execute('SELECT * FROM agent_steps WHERE run_id=? ORDER BY sequence', (identity,))]
        for step in result['steps']:
            step['input'] = json.loads(step.pop('input_document'))
            output = step.pop('output_document')
            step['output'] = json.loads(output) if output else None
        return result

    def start_job(self, kind: str) -> str:
        identity = str(uuid4())
        with self.connection() as conn:
            stamp = now()
            conn.execute("INSERT INTO jobs VALUES (?, ?, 'running', '', ?, ?)", (identity, kind, stamp, stamp))
        return identity

    def finish_job(self, identity: str, status: str, detail: str):
        with self.connection() as conn:
            conn.execute("UPDATE jobs SET status=?, detail=?, updated_at=? WHERE id=?", (status, detail, now(), identity))

    def jobs(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 12")]

    def channel(self) -> dict:
        with self.connection() as conn:
            return json.loads(conn.execute("SELECT document FROM channel_profiles WHERE id='us-extreme'").fetchone()["document"])

    def feeds(self) -> list[dict]:
        with self.connection() as conn:
            result = [dict(row) for row in conn.execute('SELECT * FROM feeds ORDER BY id')]
        for feed in result:
            feed['enabled'] = bool(feed['enabled'])
        return result

    def configure_feed(self, identity: str, enabled: bool, interval: int):
        with self.connection() as conn:
            if not conn.execute('SELECT 1 FROM feeds WHERE id=?', (identity,)).fetchone():
                raise KeyError(identity)
            conn.execute('UPDATE feeds SET enabled=?, interval_seconds=?, next_poll_at=? WHERE id=?', (int(enabled), interval, now() if enabled else None, identity))

    def schedule_feed(self, identity: str, due: str | None):
        with self.connection() as conn:
            conn.execute('UPDATE feeds SET next_poll_at=? WHERE id=?', (due, identity))

    def attempt_feed(self, identity: str):
        with self.connection() as conn:
            conn.execute("UPDATE feeds SET last_attempt_at=?, status='collecting' WHERE id=?", (now(), identity))

    def fail_feed(self, identity: str, error: str):
        with self.connection() as conn:
            conn.execute("UPDATE feeds SET status='failed', consecutive_failures=consecutive_failures+1, last_error=? WHERE id=?", (error, identity))

    def complete_feed(self, identity: str, items: list[Advisory], rejected: list[dict]) -> int:
        import hashlib
        with self.connection() as conn:
            inserted = sum(self._insert_advisory(conn, item) for item in items)
            conn.execute('DELETE FROM feed_members WHERE feed_id=?', (identity,))
            conn.executemany('INSERT OR IGNORE INTO feed_members VALUES (?, ?)', [(identity, item.id) for item in items])
            for item in items:
                conn.execute('UPDATE rejected_evidence SET resolved_at=? WHERE feed_id=? AND source_identifier IN (?, ?)', (now(), identity, item.id, item.source_url))
            for item in rejected:
                payload = json.dumps(item['payload'], sort_keys=True)
                checksum = hashlib.sha256((identity + payload).encode()).hexdigest()
                conn.execute('INSERT INTO rejected_evidence(id, feed_id, source_identifier, reason, payload, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at, reason=excluded.reason, resolved_at=NULL', (checksum, identity, item['identifier'], item['reason'], payload, now(), now()))
            conn.execute('UPDATE feeds SET last_success_at=?, consecutive_failures=0, last_error=NULL, status=?, collected_count=?, inserted_count=?, rejected_count=? WHERE id=?', (now(), 'degraded' if rejected else 'healthy', len(items), inserted, len(rejected), identity))
        return inserted

    def memberships(self) -> dict[str, set[str]]:
        with self.connection() as conn:
            result = {}
            for row in conn.execute('SELECT * FROM feed_members'):
                result.setdefault(row['feed_id'], set()).add(row['advisory_id'])
            return result

    def cache(self, url: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM http_cache WHERE url=?', (url,)).fetchone()
            return dict(row) if row else None

    def cache_response(self, url: str, body: str, etag: str | None, last_modified: str | None):
        import hashlib
        with self.connection() as conn:
            conn.execute('INSERT INTO http_cache VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified, body=excluded.body, checksum=excluded.checksum, checked_at=excluded.checked_at', (url, etag, last_modified, body, hashlib.sha256(body.encode()).hexdigest(), now()))

    def recheck_cache(self, url: str):
        with self.connection() as conn:
            conn.execute('UPDATE http_cache SET checked_at=? WHERE url=?', (now(), url))

    def quarantine(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute('SELECT id, feed_id, source_identifier, reason, first_seen_at, last_seen_at FROM rejected_evidence WHERE resolved_at IS NULL ORDER BY last_seen_at DESC LIMIT 100')]

    def save_events(self, events: list[dict]):
        with self.connection() as conn:
            conn.execute('DELETE FROM news_events')
            conn.executemany('INSERT INTO news_events VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET document=excluded.document, updated_at=excluded.updated_at', [(event['id'], json.dumps(event), now()) for event in events])
