"""Extended SQLite database for the Clipper web app.

Extends the base clipper.db.Database with additional tables for:
- accounts (multi-account social publishing)  
- sources (stream sources with per-source settings)
- settings (key-value app settings)
- posts_v2 (idempotency-keyed publishing records)
- schedules (future-scheduled posts)

Applies migrations automatically at startup.
"""

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("clipper.web.db_web")


class WebDatabase:
    """Thread-safe SQLite database for the web app (accounts, sources, settings, posts)."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        id TEXT PRIMARY KEY,
                        label TEXT NOT NULL,
                        upload_post_api_key_enc TEXT NOT NULL,
                        profile_name TEXT,
                        platforms_enabled TEXT NOT NULL DEFAULT '["youtube","instagram"]',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        daily_limit_youtube INTEGER NOT NULL DEFAULT 10,
                        daily_limit_instagram INTEGER NOT NULL DEFAULT 10,
                        daily_limit_tiktok INTEGER NOT NULL DEFAULT 5,
                        min_gap_seconds INTEGER NOT NULL DEFAULT 300,
                        timezone TEXT NOT NULL DEFAULT 'UTC',
                        auto_approve INTEGER NOT NULL DEFAULT 0,
                        caption_suffix TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sources (
                        id TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        label TEXT,
                        chunk_seconds INTEGER NOT NULL DEFAULT 90,
                        overlap_seconds INTEGER NOT NULL DEFAULT 15,
                        max_clips INTEGER NOT NULL DEFAULT 10,
                        i_own_or_have_permission INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'idle',
                        target_account_ids TEXT NOT NULL DEFAULT '[]',
                        output_dir TEXT,
                        created_at REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS posts_v2 (
                        id TEXT PRIMARY KEY,
                        clip_id TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        request_id TEXT,
                        error TEXT,
                        scheduled_at REAL,
                        posted_at REAL,
                        created_at REAL NOT NULL,
                        UNIQUE(clip_id, account_id, platform)
                    );

                    CREATE TABLE IF NOT EXISTS schedules (
                        id TEXT PRIMARY KEY,
                        clip_id TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        scheduled_at REAL NOT NULL,
                        caption_override TEXT,
                        title_override TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at REAL NOT NULL
                    );
                """)
                conn.commit()
                self._apply_migrations(conn)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Add columns that may be missing from older schema versions."""
        existing = {
            row[0]: set(r[1] for r in conn.execute(f"PRAGMA table_info({row[0]})").fetchall())
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        migrations = [
            ("accounts", "caption_suffix", "TEXT NOT NULL DEFAULT ''"),
            ("sources", "output_dir", "TEXT"),
        ]
        for table, col, col_def in migrations:
            if table in existing and col not in existing[table]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                    conn.commit()
                    logger.info("Migration: added %s.%s", table, col)
                except Exception as e:
                    logger.warning("Migration skipped %s.%s: %s", table, col, e)

    # ── Accounts ──────────────────────────────────────────────────────────────

    def create_account(
        self,
        label: str,
        upload_post_api_key_enc: str,
        profile_name: Optional[str] = None,
        platforms_enabled: Optional[List[str]] = None,
        enabled: bool = True,
        daily_limit_youtube: int = 10,
        daily_limit_instagram: int = 10,
        daily_limit_tiktok: int = 5,
        min_gap_seconds: int = 300,
        timezone: str = "UTC",
        auto_approve: bool = False,
        caption_suffix: str = "",
    ) -> str:
        account_id = str(uuid.uuid4())
        platforms = json.dumps(platforms_enabled or ["youtube", "instagram"])
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO accounts
                       (id,label,upload_post_api_key_enc,profile_name,platforms_enabled,
                        enabled,daily_limit_youtube,daily_limit_instagram,daily_limit_tiktok,
                        min_gap_seconds,timezone,auto_approve,caption_suffix,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (account_id, label, upload_post_api_key_enc, profile_name, platforms,
                     1 if enabled else 0, daily_limit_youtube, daily_limit_instagram,
                     daily_limit_tiktok, min_gap_seconds, timezone,
                     1 if auto_approve else 0, caption_suffix, time.time()),
                )
                conn.commit()
        return account_id

    def update_account(self, account_id: str, **fields) -> bool:
        allowed = {
            "label", "upload_post_api_key_enc", "profile_name", "platforms_enabled",
            "enabled", "daily_limit_youtube", "daily_limit_instagram", "daily_limit_tiktok",
            "min_gap_seconds", "timezone", "auto_approve", "caption_suffix",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        # Serialize list fields
        if "platforms_enabled" in updates and isinstance(updates["platforms_enabled"], list):
            updates["platforms_enabled"] = json.dumps(updates["platforms_enabled"])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [account_id]
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)
                conn.commit()
                return cur.rowcount > 0

    def delete_account(self, account_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                conn.commit()
                return cur.rowcount > 0

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
                return self._parse_account(dict(row)) if row else None

    def list_accounts(self) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM accounts ORDER BY created_at ASC").fetchall()
                return [self._parse_account(dict(r)) for r in rows]

    def _parse_account(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            row["platforms_enabled"] = json.loads(row.get("platforms_enabled") or "[]")
        except Exception:
            row["platforms_enabled"] = []
        return row

    # ── Sources ───────────────────────────────────────────────────────────────

    def create_source(
        self,
        url: str,
        label: Optional[str] = None,
        chunk_seconds: int = 90,
        overlap_seconds: int = 15,
        max_clips: int = 10,
        i_own_or_have_permission: bool = False,
        target_account_ids: Optional[List[str]] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        source_id = str(uuid.uuid4())
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO sources
                       (id,url,label,chunk_seconds,overlap_seconds,max_clips,
                        i_own_or_have_permission,status,target_account_ids,output_dir,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (source_id, url, label or url[:60], chunk_seconds, overlap_seconds,
                     max_clips, 1 if i_own_or_have_permission else 0, "idle",
                     json.dumps(target_account_ids or []), output_dir, time.time()),
                )
                conn.commit()
        return source_id

    def update_source(self, source_id: str, **fields) -> bool:
        allowed = {
            "url", "label", "chunk_seconds", "overlap_seconds", "max_clips",
            "i_own_or_have_permission", "status", "target_account_ids", "output_dir",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "target_account_ids" in updates and isinstance(updates["target_account_ids"], list):
            updates["target_account_ids"] = json.dumps(updates["target_account_ids"])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [source_id]
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(f"UPDATE sources SET {set_clause} WHERE id = ?", values)
                conn.commit()
                return cur.rowcount > 0

    def delete_source(self, source_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
                conn.commit()
                return cur.rowcount > 0

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
                return self._parse_source(dict(row)) if row else None

    def list_sources(self) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM sources ORDER BY created_at ASC").fetchall()
                return [self._parse_source(dict(r)) for r in rows]

    def _parse_source(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            row["target_account_ids"] = json.loads(row.get("target_account_ids") or "[]")
        except Exception:
            row["target_account_ids"] = []
        return row

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
                if row is None:
                    return default
                try:
                    return json.loads(row["value"])
                except Exception:
                    return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO settings (key,value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, serialized),
                )
                conn.commit()

    def get_all_settings(self) -> Dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT key, value FROM settings").fetchall()
                result = {}
                for row in rows:
                    try:
                        result[row["key"]] = json.loads(row["value"])
                    except Exception:
                        result[row["key"]] = row["value"]
                return result

    # ── Posts v2 ──────────────────────────────────────────────────────────────

    def upsert_post_v2(
        self,
        clip_id: str,
        account_id: str,
        platform: str,
        status: str = "pending",
        request_id: Optional[str] = None,
        error: Optional[str] = None,
        scheduled_at: Optional[float] = None,
        posted_at: Optional[float] = None,
    ) -> str:
        """Insert or update a post record. Returns post id."""
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM posts_v2 WHERE clip_id=? AND account_id=? AND platform=?",
                    (clip_id, account_id, platform),
                ).fetchone()
                if existing:
                    post_id = existing["id"]
                    conn.execute(
                        """UPDATE posts_v2 SET status=?,request_id=COALESCE(?,request_id),
                           error=?,scheduled_at=COALESCE(?,scheduled_at),
                           posted_at=COALESCE(?,posted_at)
                           WHERE id=?""",
                        (status, request_id, error, scheduled_at, posted_at, post_id),
                    )
                else:
                    post_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO posts_v2
                           (id,clip_id,account_id,platform,status,request_id,error,
                            scheduled_at,posted_at,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (post_id, clip_id, account_id, platform, status, request_id,
                         error, scheduled_at, posted_at, time.time()),
                    )
                conn.commit()
                return post_id

    def is_posted_v2(self, clip_id: str, account_id: str, platform: str) -> bool:
        """Check idempotency: has this (clip, account, platform) already been posted?"""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM posts_v2 WHERE clip_id=? AND account_id=? AND platform=? AND status='posted'",
                    (clip_id, account_id, platform),
                ).fetchone()
                return row is not None

    def list_posts_v2(
        self,
        clip_id: Optional[str] = None,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if clip_id:
            clauses.append("clip_id = ?")
            params.append(clip_id)
        if account_id:
            clauses.append("account_id = ?")
            params.append(account_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM posts_v2 {where} ORDER BY created_at DESC LIMIT ?",
                    params,
                ).fetchall()
                return [dict(r) for r in rows]

    def count_posts_v2_today(self, account_id: str, platform: str) -> int:
        since = time.time() - 86400.0
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as n FROM posts_v2 WHERE account_id=? AND platform=? AND status='posted' AND posted_at>=?",
                    (account_id, platform, since),
                ).fetchone()
                return int(row["n"]) if row else 0

    def last_post_time_v2(self, account_id: str, platform: str) -> Optional[float]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT MAX(posted_at) as t FROM posts_v2 WHERE account_id=? AND platform=? AND status='posted'",
                    (account_id, platform),
                ).fetchone()
                return float(row["t"]) if row and row["t"] else None

    def posts_today_count(self) -> Dict[str, int]:
        """Return {account_id:platform -> count} for dashboard."""
        since = time.time() - 86400.0
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT account_id, platform, COUNT(*) as n FROM posts_v2 "
                    "WHERE status='posted' AND posted_at>=? GROUP BY account_id, platform",
                    (since,),
                ).fetchall()
                return {f"{r['account_id']}:{r['platform']}": r["n"] for r in rows}
