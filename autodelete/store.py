from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    label TEXT NOT NULL,
    credentials TEXT NOT NULL,
    rules TEXT NOT NULL,
    live INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    last_status TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    post_id TEXT,
    post_url TEXT,
    post_text TEXT,
    post_date TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS archived_posts (
    account_id INTEGER NOT NULL,
    post_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (account_id, post_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {"schedule_enabled": "1", "interval_hours": "24"}


def default_db_path() -> Path:
    if os.environ.get("AUTODELETE_DB"):
        return Path(os.environ["AUTODELETE_DB"])
    if getattr(sys, "frozen", False):
        # Packaged app: the working directory may be read-only (e.g. "/" when double-clicked on macOS),
        # so keep data in the usual per-user location.
        return user_data_dir() / "autodelete.db"
    return Path.cwd() / "data" / "autodelete.db"


def user_data_dir() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "AutoDeletePosts"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "AutoDeletePosts"
    return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share")) / "autodeleteposts"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if str(self.path) != ":memory:":
            # Credentials live in this file, so keep it private to the current user.
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    @property
    def data_dir(self) -> Path:
        """Folder for files that sit next to the database (browser logins, debug screenshots)."""
        if str(self.path) == ":memory:":
            return Path(tempfile.gettempdir()) / "autodelete-memory"
        return self.path.parent

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    # --- accounts ------------------------------------------------------------
    def _account(self, row: sqlite3.Row) -> dict:
        acc = dict(row)
        acc["credentials"] = json.loads(acc["credentials"])
        acc["rules"] = json.loads(acc["rules"])
        acc["live"] = bool(acc["live"])
        acc["enabled"] = bool(acc["enabled"])
        return acc

    def accounts(self) -> list[dict]:
        return [self._account(r) for r in self._all("SELECT * FROM accounts ORDER BY id")]

    def account(self, account_id: int) -> dict | None:
        rows = self._all("SELECT * FROM accounts WHERE id = ?", (account_id,))
        return self._account(rows[0]) if rows else None

    def add_account(self, platform: str, label: str, credentials: dict, rules: dict,
                    live: bool = False, enabled: bool = True) -> int:
        cur = self._exec(
            "INSERT INTO accounts (platform, label, credentials, rules, live, enabled) VALUES (?,?,?,?,?,?)",
            (platform, label, json.dumps(credentials), json.dumps(rules), int(live), int(enabled)),
        )
        return cur.lastrowid

    def update_account(self, account_id: int, **fields) -> None:
        cols, args = [], []
        for key, value in fields.items():
            if key in ("credentials", "rules"):
                value = json.dumps(value)
            elif key in ("live", "enabled"):
                value = int(bool(value))
            cols.append(f"{key} = ?")
            args.append(value)
        if cols:
            self._exec(f"UPDATE accounts SET {', '.join(cols)} WHERE id = ?", (*args, account_id))

    def delete_account(self, account_id: int) -> None:
        self._exec("DELETE FROM accounts WHERE id = ?", (account_id,))
        self._exec("DELETE FROM history WHERE account_id = ?", (account_id,))
        self._exec("DELETE FROM archived_posts WHERE account_id = ?", (account_id,))

    # --- imported archives (posts too old for the live timeline) -------------------------
    def set_archive(self, account_id: int, items: list[dict]) -> None:
        with self._lock:
            self.db.execute("DELETE FROM archived_posts WHERE account_id = ?", (account_id,))
            self.db.executemany(
                "INSERT OR REPLACE INTO archived_posts (account_id, post_id, data) VALUES (?,?,?)",
                [(account_id, item["id"], json.dumps(item)) for item in items])
            self.db.commit()

    def archive(self, account_id: int) -> list[dict]:
        rows = self._all("SELECT data FROM archived_posts WHERE account_id = ?", (account_id,))
        return [json.loads(r["data"]) for r in rows]

    def archive_count(self, account_id: int) -> int:
        return self._all("SELECT COUNT(*) AS n FROM archived_posts WHERE account_id = ?", (account_id,))[0]["n"]

    def forget_archived(self, account_id: int, post_id: str) -> None:
        self._exec("DELETE FROM archived_posts WHERE account_id = ? AND post_id = ?", (account_id, post_id))

    # --- history -------------------------------------------------------------
    def log(self, account_id: int, action: str, post=None, detail: str = "") -> None:
        self._exec(
            "INSERT INTO history (account_id, ts, action, post_id, post_url, post_text, post_date, detail)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                account_id,
                now_iso(),
                action,
                getattr(post, "id", None),
                getattr(post, "url", None),
                (getattr(post, "text", "") or "")[:500],
                post.created_at.isoformat() if post is not None else None,
                detail,
            ),
        )

    def history(self, limit: int = 200, account_id: int | None = None) -> list[dict]:
        sql = ("SELECT h.*, a.label, a.platform FROM history h "
               "LEFT JOIN accounts a ON a.id = h.account_id")
        args: tuple = ()
        if account_id is not None:
            sql += " WHERE h.account_id = ?"
            args = (account_id,)
        sql += " ORDER BY h.id DESC LIMIT ?"
        return [dict(r) for r in self._all(sql, (*args, limit))]

    def deleted_count(self, account_id: int) -> int:
        rows = self._all("SELECT COUNT(*) AS n FROM history WHERE account_id = ? AND action = 'deleted'",
                         (account_id,))
        return rows[0]["n"]

    # --- settings ------------------------------------------------------------
    def setting(self, key: str) -> str:
        rows = self._all("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
