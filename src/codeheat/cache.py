"""Tiny SQLite key/value cache for per-blob complexity results."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class BlobCache:
    def __init__(self, directory: Path | None, enabled: bool = True):
        self.conn: sqlite3.Connection | None = None
        if not enabled or directory is None:
            return
        try:
            directory.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(directory / "metrics-v1.sqlite3"), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("CREATE TABLE IF NOT EXISTS m (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            conn.commit()
            self.conn = conn
        except (OSError, sqlite3.Error):
            self.conn = None

    def get_many(self, keys: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not self.conn:
            return out
        try:
            for i in range(0, len(keys), 500):
                part = keys[i : i + 500]
                q = "SELECT k, v FROM m WHERE k IN (%s)" % ",".join("?" * len(part))
                for k, v in self.conn.execute(q, part):
                    out[k] = json.loads(v)
        except (sqlite3.Error, ValueError):
            pass
        return out

    def put_many(self, items: dict[str, dict]) -> None:
        if not self.conn or not items:
            return
        try:
            with self.conn:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO m (k, v) VALUES (?, ?)",
                    [(k, json.dumps(v, separators=(",", ":"))) for k, v in items.items()],
                )
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
