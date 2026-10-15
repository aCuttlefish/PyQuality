import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from backend.config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        init_db(_conn)
    return _conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            file_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            last_analysis TEXT
        );
        CREATE TABLE IF NOT EXISTS project_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            UNIQUE(project_id, rel_path),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analysis_cache (
            project_id TEXT PRIMARY KEY,
            result TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()


def create_project(name: str, description: str, files: list[dict], pid: str | None = None) -> dict:
    with _lock:
        conn = get_conn()
        pid = pid or uuid.uuid4().hex[:12]
        now = time.time()
        conn.execute(
            "INSERT INTO projects (id, name, description, file_count, created_at) VALUES (?,?,?,?,?)",
            (pid, name, description, len(files), now),
        )
        conn.executemany(
            "INSERT INTO project_files (project_id, rel_path, size) VALUES (?,?,?)",
            [(pid, f["rel_path"], f.get("size", 0)) for f in files],
        )
        conn.commit()
        return get_project(pid)


def get_project(pid: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if row is None:
        return None
    return dict(row)


def list_projects() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def list_files(pid: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT rel_path, size FROM project_files WHERE project_id=? ORDER BY rel_path",
        (pid,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_project(pid: str) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.execute("DELETE FROM project_files WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM analysis_cache WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM analysis_history WHERE project_id=?", (pid,))
        conn.commit()
        return cur.rowcount > 0


def rename_project(pid: str, name: str) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.execute("UPDATE projects SET name=? WHERE id=?", (name, pid))
        conn.commit()
        return cur.rowcount > 0


def save_analysis(pid: str, result: str) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO analysis_cache (project_id, result, created_at) VALUES (?,?,?)",
            (pid, result, time.time()),
        )
        conn.execute(
            "UPDATE projects SET last_analysis=? WHERE id=?",
            (time.strftime("%Y-%m-%d %H:%M:%S"), pid),
        )
        conn.commit()


def get_analysis(pid: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT result FROM analysis_cache WHERE project_id=?", (pid,)
    ).fetchone()
    return row["result"] if row else None


def get_file_abs_path(pid: str, rel_path: str) -> Path | None:
    from backend.config import UPLOAD_DIR

    base = (UPLOAD_DIR / pid).resolve()
    target = (base / rel_path).resolve()
    if not str(target).startswith(str(base)):
        return None
    return target if target.exists() else None


def update_project_stats(pid: str) -> None:
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM project_files WHERE project_id=?", (pid,)
    ).fetchone()["c"]
    conn.execute("UPDATE projects SET file_count=? WHERE id=?", (count, pid))
    conn.commit()

def save_analysis_history(pid: str, summary: dict) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO analysis_history (project_id, summary, created_at) VALUES (?,?,?)",
            (pid, json.dumps(summary, ensure_ascii=False), time.time()),
        )
        conn.commit()


def list_analysis_history(pid: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, summary, created_at FROM analysis_history WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (pid, limit),
    ).fetchall()
    return [{"id": r["id"], "summary": json.loads(r["summary"]), "created_at": r["created_at"]} for r in rows]
