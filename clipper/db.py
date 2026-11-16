"""SQLite persistence layer for Live Stream Clipper.

Maintains atomic, crash-resilient state for chunks, processing jobs, clips,
social media publication records, and deduplication hashes.
"""

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union


class Database:
    """Thread-safe SQLite database manager for pipeline state."""

    def __init__(self, db_path: Path):
        """Initialize the database connection and apply schema migrations.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding a properly configured connection that is closed on exit."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Create tables if they do not exist."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chunks (
                        id TEXT PRIMARY KEY,
                        path TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        chunk_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        result_json TEXT,
                        FOREIGN KEY (chunk_id) REFERENCES chunks(id)
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS clips (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        path TEXT NOT NULL,
                        approved INT DEFAULT 0,
                        posted_platforms TEXT DEFAULT '[]',
                        created_at REAL NOT NULL,
                        FOREIGN KEY (job_id) REFERENCES jobs(id)
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS posts (
                        id TEXT PRIMARY KEY,
                        clip_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        status TEXT NOT NULL,
                        remote_id TEXT,
                        created_at REAL NOT NULL,
                        FOREIGN KEY (clip_id) REFERENCES clips(id)
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS posted_hashes (
                        hash TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        posted_at REAL NOT NULL,
                        PRIMARY KEY (hash, platform)
                    );
                """)
                conn.commit()

    def upsert_chunk(self, chunk_id: str, path: str, status: str, created_at: Optional[float] = None) -> None:
        """Insert or update a stream chunk record."""
        ts = created_at if created_at is not None else time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO chunks (id, path, status, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        path = excluded.path,
                        status = excluded.status;
                    """,
                    (chunk_id, path, status, ts),
                )
                conn.commit()

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a chunk record by id."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
                return dict(row) if row else None

    def upsert_job(
        self,
        job_id: str,
        chunk_id: str,
        status: str,
        result_json: Optional[Union[str, Dict[str, Any]]] = None,
        created_at: Optional[float] = None,
    ) -> None:
        """Insert or update an OpenShorts processing job."""
        ts = created_at if created_at is not None else time.time()
        if isinstance(result_json, (dict, list)):
            result_str = json.dumps(result_json)
        else:
            result_str = result_json

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (id, chunk_id, status, created_at, result_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status = excluded.status,
                        result_json = coalesce(excluded.result_json, jobs.result_json);
                    """,
                    (job_id, chunk_id, status, ts, result_str),
                )
                conn.commit()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a job by id."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return dict(row) if row else None

    def upsert_clip(
        self,
        clip_id: str,
        job_id: str,
        title: str,
        path: str,
        approved: int = 0,
        posted_platforms: Optional[Union[str, List[str]]] = None,
        created_at: Optional[float] = None,
    ) -> None:
        """Insert or update an extracted clip."""
        ts = created_at if created_at is not None else time.time()
        if isinstance(posted_platforms, list):
            platforms_str = json.dumps(posted_platforms)
        elif posted_platforms is None:
            platforms_str = "[]"
        else:
            platforms_str = posted_platforms

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO clips (id, job_id, title, path, approved, posted_platforms, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        path = excluded.path,
                        approved = excluded.approved,
                        posted_platforms = excluded.posted_platforms;
                    """,
                    (clip_id, job_id, title, path, approved, platforms_str, ts),
                )
                conn.commit()

    def get_clip(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a clip record by id."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
                if not row:
                    return None
                data = dict(row)
                try:
                    data["posted_platforms"] = json.loads(data["posted_platforms"])
                except Exception:
                    data["posted_platforms"] = []
                return data

    def mark_clip_approved(self, clip_id: str, new_path: Optional[str] = None) -> None:
        """Mark a clip as approved (approved = 1) and optionally update its path."""
        with self._lock:
            with self._connect() as conn:
                if new_path:
                    conn.execute("UPDATE clips SET approved = 1, path = ? WHERE id = ?", (new_path, clip_id))
                else:
                    conn.execute("UPDATE clips SET approved = 1 WHERE id = ?", (clip_id,))
                conn.commit()

    def mark_clip_rejected(self, clip_id: str, new_path: Optional[str] = None) -> None:
        """Mark a clip as rejected (approved = -1) and optionally update its path."""
        with self._lock:
            with self._connect() as conn:
                if new_path:
                    conn.execute("UPDATE clips SET approved = -1, path = ? WHERE id = ?", (new_path, clip_id))
                else:
                    conn.execute("UPDATE clips SET approved = -1 WHERE id = ?", (clip_id,))
                conn.commit()

    def mark_clip_posted(self, clip_id: str, platform: str) -> None:
        """Add a platform to the clip's posted_platforms list if not already present."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT posted_platforms FROM clips WHERE id = ?", (clip_id,)).fetchone()
                if row:
                    try:
                        platforms = json.loads(row["posted_platforms"])
                    except Exception:
                        platforms = []
                    if platform not in platforms:
                        platforms.append(platform)
                        conn.execute(
                            "UPDATE clips SET posted_platforms = ? WHERE id = ?",
                            (json.dumps(platforms), clip_id),
                        )
                        conn.commit()
                else:
                    conn.execute(
                        """
                        INSERT INTO clips (id, job_id, title, path, approved, posted_platforms, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (clip_id, "unknown", clip_id, "", 1, json.dumps([platform]), time.time()),
                    )
                    conn.commit()

    def upsert_post(
        self,
        post_id: str,
        clip_id: str,
        platform: str,
        status: str,
        remote_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> None:
        """Insert or update a social media posting attempt."""
        ts = created_at if created_at is not None else time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO posts (id, clip_id, platform, status, remote_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status = excluded.status,
                        remote_id = coalesce(excluded.remote_id, posts.remote_id);
                    """,
                    (post_id, clip_id, platform, status, remote_id, ts),
                )
                conn.commit()

    def is_already_posted(self, hash_val: str, platform: str) -> bool:
        """Check if content hash has already been posted to the given platform."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM posted_hashes WHERE hash = ? AND platform = ?",
                    (hash_val, platform),
                ).fetchone()
                return row is not None

    def mark_posted(self, hash_val: str, platform: str, posted_at: Optional[float] = None) -> None:
        """Record a successful posting hash for idempotency."""
        ts = posted_at if posted_at is not None else time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO posted_hashes (hash, platform, posted_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(hash, platform) DO UPDATE SET
                        posted_at = excluded.posted_at;
                    """,
                    (hash_val, platform, ts),
                )
                conn.commit()

    def get_pending_clips(self) -> List[Dict[str, Any]]:
        """Return clips that are awaiting review (approved == 0)."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM clips WHERE approved = 0 ORDER BY created_at ASC"
                ).fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["posted_platforms"] = json.loads(item["posted_platforms"])
                    except Exception:
                        item["posted_platforms"] = []
                    results.append(item)
                return results

    def get_approved_unposted_clips(self, platform: str) -> List[Dict[str, Any]]:
        """Return approved clips (approved == 1) not yet recorded as posted to platform."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM clips WHERE approved = 1 ORDER BY created_at ASC"
                ).fetchall()
                unposted = []
                for row in rows:
                    item = dict(row)
                    try:
                        platforms = json.loads(item["posted_platforms"])
                    except Exception:
                        platforms = []
                    if platform not in platforms:
                        item["posted_platforms"] = platforms
                        unposted.append(item)
                return unposted

    def get_processable_chunks(self) -> List[Dict[str, Any]]:
        """Return chunks whose status is 'pending' or 'recorded'."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM chunks WHERE status IN ('pending', 'recorded') ORDER BY created_at ASC"
                ).fetchall()
                return [dict(r) for r in rows]

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        """Return all recorded chunks."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM chunks ORDER BY created_at ASC").fetchall()
                return [dict(r) for r in rows]

    def count_recent_posts(self, platform: str, window_seconds: float = 86400.0) -> int:
        """Count successful posts for a platform within a sliding time window (default 24h)."""
        since = time.time() - window_seconds
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as count FROM posts
                    WHERE platform = ? AND status IN ('posted', 'success') AND created_at >= ?
                    """,
                    (platform, since),
                ).fetchone()
                return int(row["count"]) if row else 0

    def get_last_post_time(self, platform: str) -> Optional[float]:
        """Return the timestamp of the most recent post for a platform."""
        since = time.time()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT MAX(created_at) as last_time FROM posts
                    WHERE platform = ? AND status IN ('posted', 'success')
                    """,
                    (platform,),
                ).fetchone()
                if row and row["last_time"] is not None:
                    return float(row["last_time"])
                return None

    def resume_state(self) -> Dict[str, Any]:
        """Load resume state for crash recovery."""
        with self._lock:
            with self._connect() as conn:
                pending_chunks = conn.execute(
                    "SELECT * FROM chunks WHERE status NOT IN ('completed', 'failed')"
                ).fetchall()
                active_jobs = conn.execute(
                    "SELECT * FROM jobs WHERE status IN ('queued', 'processing')"
                ).fetchall()
                pending_review = conn.execute(
                    "SELECT * FROM clips WHERE approved = 0"
                ).fetchall()
                approved_clips = conn.execute(
                    "SELECT * FROM clips WHERE approved = 1"
                ).fetchall()
                return {
                    "pending_chunks": [dict(r) for r in pending_chunks],
                    "active_jobs": [dict(r) for r in active_jobs],
                    "pending_review": [dict(r) for r in pending_review],
                    "approved_clips": [dict(r) for r in approved_clips],
                }
