import os
import sqlite3
import datetime
from typing import Optional, List, Dict

DB_PATH = "data/emby_doctor.db"

class Database:
    def __init__(self, db_path: str = DB_PATH):
        os.makedirs("data", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS media_status ("
            "emby_id TEXT PRIMARY KEY,"
            "name TEXT,"
            "path TEXT,"
            "status TEXT,"
            "retry_count INTEGER DEFAULT 0,"
            "last_update TIMESTAMP,"
            "meta_info TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS system_config ("
            "key TEXT PRIMARY KEY,"
            "value TEXT)"
        )
        self.conn.commit()

    def get_media_status(self, emby_id: str) -> Optional[Dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM media_status WHERE emby_id = ?", (emby_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {k: row[k] for k in row.keys()}

    def set_media_status(
        self,
        emby_id: str,
        name: str,
        path: str,
        status: str,
        meta_info: Optional[str] = None,
        increment_retry: bool = False,
    ):
        now = datetime.datetime.utcnow().isoformat() + "Z"
        existing = self.get_media_status(emby_id)
        retry = 0
        if existing:
            retry = int(existing.get("retry_count") or 0)
        if increment_retry:
            retry += 1
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO media_status (emby_id, name, path, status, retry_count, last_update, meta_info) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(emby_id) DO UPDATE SET "
            "name=excluded.name, path=excluded.path, status=excluded.status, "
            "retry_count=excluded.retry_count, last_update=excluded.last_update, meta_info=excluded.meta_info",
            (emby_id, name, path, status, retry, now, meta_info),
        )
        self.conn.commit()

    def get_all_ids(self) -> List[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT emby_id FROM media_status")
        return [row[0] for row in cur.fetchall()]

    def delete_ids(self, ids: List[str]) -> int:
        if not ids:
            return 0
        cur = self.conn.cursor()
        total = 0
        batch_size = 900
        for i in range(0, len(ids), batch_size):
            chunk = ids[i : i + batch_size]
            placeholders = ",".join(["?"] * len(chunk))
            cur.execute(f"DELETE FROM media_status WHERE emby_id IN ({placeholders})", chunk)
            total += cur.rowcount
        self.conn.commit()
        return total

    def get_stats(self) -> Dict[str, int]:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM media_status WHERE status = 'success'")
        success = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM media_status WHERE status = 'failed'")
        failed = cur.fetchone()[0]
        return {"success": success, "failed": failed}

    def get_config(self, key: str) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_config(self, key: str, value: str):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO system_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()
