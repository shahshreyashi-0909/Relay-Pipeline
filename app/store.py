"""SQLite persistence for jobs and brand voice profiles."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "relay.db"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, title TEXT, data TEXT, created_at REAL, updated_at REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS voices (id TEXT PRIMARY KEY, name TEXT, data TEXT, updated_at REAL)")


def save_job(job: dict) -> dict:
    now = time.time()
    job.setdefault("id", uuid.uuid4().hex[:10])
    job.setdefault("created_at", now)
    job["updated_at"] = now
    with _conn() as c:
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, data=excluded.data, updated_at=excluded.updated_at",
                  (job["id"], job.get("title", ""), json.dumps(job), job["created_at"], job["updated_at"]))
    return job


def get_job(jid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
    return json.loads(r["data"]) if r else None


def list_jobs() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, title, data, updated_at FROM jobs ORDER BY updated_at DESC LIMIT 50").fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        out.append({"id": r["id"], "title": r["title"] or "Untitled", "updated_at": r["updated_at"],
                    "overall": d.get("overall"), "platforms": list(d.get("drafts", {}).keys()),
                    "words": d.get("source", {}).get("word_count")})
    return out


def delete_job(jid: str):
    with _conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (jid,))


def save_voice(v: dict) -> dict:
    v.setdefault("id", uuid.uuid4().hex[:8])
    with _conn() as c:
        c.execute("INSERT INTO voices VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, data=excluded.data, updated_at=excluded.updated_at",
                  (v["id"], v.get("name", "Brand voice"), json.dumps(v), time.time()))
    return v


def list_voices() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM voices ORDER BY updated_at DESC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def delete_voice(vid: str):
    with _conn() as c:
        c.execute("DELETE FROM voices WHERE id=?", (vid,))
