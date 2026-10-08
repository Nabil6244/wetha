import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .contracts import Advisory


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def scripts(self) -> list[dict]:
        with self.connection() as conn:
            return [json.loads(r["document"]) for r in conn.execute("SELECT document FROM scripts ORDER BY created_at DESC")]

    def review_script(self, identity: str, reviewer: str):
        with self.connection() as conn:
            row = conn.execute("SELECT document FROM scripts WHERE id=?", (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            document = json.loads(row["document"])
            document.update(status="reviewed", reviewer=reviewer, reviewed_at=now())
            for check in document["qc"]:
                if check["check"] == "Human editorial review":
                    check["passed"] = True
            conn.execute("UPDATE scripts SET document=? WHERE id=?", (json.dumps(document), identity))
            return document

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
