"""
ZipStreamHub History & Bookmarks Manager
Persistent SQLite storage for inspected archives, quick bookmarks/favorites, and playback history.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "history.db"


class HistoryManager:
    """
    Thread-safe persistent storage for inspected archives and favorites using SQLite.
    """

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables and indices if they do not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT UNIQUE NOT NULL,
                        title TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        file_count INTEGER NOT NULL DEFAULT 0,
                        is_favorite INTEGER NOT NULL DEFAULT 0,
                        last_accessed_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_url ON history(url)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_last_accessed ON history(last_accessed_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_favorite ON history(is_favorite)")
                conn.commit()
            finally:
                conn.close()

    def add_history(
        self,
        url: str,
        title: str = "",
        size_bytes: int = 0,
        file_count: int = 0,
        is_favorite: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Records or updates an archive in history. If the archive already exists,
        its timestamp is updated to now, and size/file_count/title are refreshed.
        """
        clean_url = url.strip()
        if not clean_url:
            raise ValueError("URL cannot be empty.")

        now_iso = datetime.now(timezone.utc).isoformat()
        if not title:
            title = os.path.basename(clean_url.split("?")[0]) or clean_url

        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, is_favorite FROM history WHERE url = ?", (clean_url,))
                row = cur.fetchone()

                if row:
                    fav_val = row["is_favorite"] if is_favorite is None else (1 if is_favorite else 0)
                    cur.execute("""
                        UPDATE history 
                        SET title = ?, size_bytes = ?, file_count = ?, is_favorite = ?, last_accessed_at = ?
                        WHERE url = ?
                    """, (title, size_bytes, file_count, fav_val, now_iso, clean_url))
                else:
                    fav_val = 1 if is_favorite else 0
                    cur.execute("""
                        INSERT INTO history (url, title, size_bytes, file_count, is_favorite, last_accessed_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (clean_url, title, size_bytes, file_count, fav_val, now_iso, now_iso))

                conn.commit()
            finally:
                conn.close()

        return self.get_entry(clean_url) or {}

    def get_history(self, limit: int = 20, favorites_only: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieves inspected archive history ordered by most recently accessed.
        """
        query = "SELECT * FROM history"
        params: List[Any] = []

        if favorites_only:
            query += " WHERE is_favorite = 1"

        query += " ORDER BY last_accessed_at DESC"

        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

                return [
                    {
                        "id": r["id"],
                        "url": r["url"],
                        "title": r["title"],
                        "size_bytes": r["size_bytes"],
                        "size_gb": round(r["size_bytes"] / (1024 ** 3), 2),
                        "file_count": r["file_count"],
                        "is_favorite": bool(r["is_favorite"]),
                        "last_accessed_at": r["last_accessed_at"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def get_entry(self, url: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single history record by URL."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM history WHERE url = ?", (url.strip(),))
                r = cur.fetchone()
                if not r:
                    return None
                return {
                    "id": r["id"],
                    "url": r["url"],
                    "title": r["title"],
                    "size_bytes": r["size_bytes"],
                    "size_gb": round(r["size_bytes"] / (1024 ** 3), 2),
                    "file_count": r["file_count"],
                    "is_favorite": bool(r["is_favorite"]),
                    "last_accessed_at": r["last_accessed_at"],
                    "created_at": r["created_at"],
                }
            finally:
                conn.close()

    def toggle_favorite(self, url: str) -> bool:
        """
        Toggles favorite status for an archive URL. Returns the new favorite status.
        """
        clean_url = url.strip()
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT is_favorite FROM history WHERE url = ?", (clean_url,))
                row = cur.fetchone()
                if not row:
                    # If not found, add it as favorite
                    now_iso = datetime.now(timezone.utc).isoformat()
                    title = os.path.basename(clean_url.split("?")[0]) or clean_url
                    cur.execute("""
                        INSERT INTO history (url, title, size_bytes, file_count, is_favorite, last_accessed_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (clean_url, title, 0, 0, 1, now_iso, now_iso))
                    conn.commit()
                    return True

                new_val = 0 if row["is_favorite"] else 1
                cur.execute("UPDATE history SET is_favorite = ? WHERE url = ?", (new_val, clean_url))
                conn.commit()
                return bool(new_val)
            finally:
                conn.close()

    def delete_history(self, url: str) -> bool:
        """Removes a specific archive URL from history."""
        clean_url = url.strip()
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM history WHERE url = ?", (clean_url,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def clear_history(self, keep_favorites: bool = True) -> int:
        """Clears history, optionally preserving favorites."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if keep_favorites:
                    cur.execute("DELETE FROM history WHERE is_favorite = 0")
                else:
                    cur.execute("DELETE FROM history")
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()


# Module-level singleton instance
_default_manager = HistoryManager()

def add_history(url: str, title: str = "", size_bytes: int = 0, file_count: int = 0) -> Dict[str, Any]:
    return _default_manager.add_history(url, title, size_bytes, file_count)

def get_history(limit: int = 20) -> List[Dict[str, Any]]:
    return _default_manager.get_history(limit=limit)

def toggle_favorite(url: str) -> bool:
    return _default_manager.toggle_favorite(url)

def delete_history(url: str) -> bool:
    return _default_manager.delete_history(url)
