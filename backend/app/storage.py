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

    def save_advisory(self, item: Advisory) -> bool:
        with self.connection() as conn:
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
        with self.connection() as conn:
            row = conn.execute("SELECT document FROM advisories WHERE event_key=? AND issued_at<? ORDER BY issued_at DESC LIMIT 1", (item.event_key, item.issued_at.isoformat())).fetchone()
            return Advisory.model_validate_json(row["document"]) if row else None

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
