"""SQLite state: dedupe and resume, so a re-run only pays for what is new.

A report is unique per (id, folder): the same PDF can legitimately be collected once for a stock and
once for an industry, and each folder is its own body of work.
"""
import sqlite3
from pathlib import Path

from .models import ReportMeta

SCHEMA = """
CREATE TABLE IF NOT EXISTS report_items (
  id TEXT NOT NULL, grp TEXT NOT NULL, url TEXT, title TEXT, published TEXT,
  status TEXT, saved_path TEXT, error TEXT, fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id, grp)
)"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(SCHEMA)
        self._db.commit()

    def is_done(self, report_id: str, folder: str) -> bool:
        row = self._db.execute(
            "SELECT status FROM report_items WHERE id=? AND grp=?", (report_id, folder)).fetchone()
        # empty = no text body; filtered = judged irrelevant to the stock (relevance.py). Neither is
        # worth another detail-page request, so both count as handled.
        return bool(row and row[0] in ("done", "empty", "filtered"))

    def mark(self, meta: ReportMeta, folder: str, status: str, path: str = "", error: str = "") -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO report_items(id,grp,url,title,published,status,saved_path,error)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (meta.id, folder, meta.url, meta.title, meta.published, status, path, error),
        )
        self._db.commit()

    def counts(self, folder: str | None = None) -> list[dict]:
        """Per-folder status counts, e.g. [{"folder": "个股_紫金", "done": 35, "failed": 1}, ...]."""
        sql = "SELECT grp, status, COUNT(*) FROM report_items"
        args: tuple = ()
        if folder:
            sql, args = sql + " WHERE grp=?", (folder,)
        rows = self._db.execute(sql + " GROUP BY grp, status ORDER BY grp", args).fetchall()
        merged: dict[str, dict] = {}
        for grp, status, n in rows:
            entry = merged.setdefault(grp, {"folder": grp, "done": 0, "empty": 0, "failed": 0, "filtered": 0})
            entry[status] = n
        return list(merged.values())

    def recent(self, status: str, folder: str | None = None, limit: int = 20) -> list[dict]:
        sql = "SELECT id, grp, url, title, published, error, fetched_at FROM report_items WHERE status=?"
        args: list = [status]
        if folder:
            sql, args = sql + " AND grp=?", [*args, folder]
        rows = self._db.execute(sql + " ORDER BY fetched_at DESC LIMIT ?", (*args, limit)).fetchall()
        keys = ("id", "folder", "url", "title", "published", "error", "fetched_at")
        return [dict(zip(keys, r)) for r in rows]

    def close(self) -> None:
        self._db.close()
