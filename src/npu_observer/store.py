from __future__ import annotations
import json, sqlite3, threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE,
    timestamp TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT,
    trace_id TEXT,
    session_id TEXT,
    parent_id TEXT,
    cwd TEXT,
    host TEXT,
    pid INTEGER,
    attributes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
"""

class EventStore:
    def __init__(self, path: str):
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def insert(self, event: dict) -> None:
        attrs = event.get("attributes", {})
        with self._lock:
            self.conn.execute(
                """INSERT OR IGNORE INTO events
                (event_id,timestamp,name,kind,source,trace_id,session_id,parent_id,cwd,host,pid,attributes_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.get("event_id"), event.get("timestamp"), event.get("name"), event.get("kind","event"),
                    event.get("source"), event.get("trace_id"), event.get("session_id"), event.get("parent_id"),
                    event.get("cwd"), event.get("host"), event.get("pid"), json.dumps(attrs, ensure_ascii=False),
                ),
            )
            self.conn.commit()

    def rows(self, limit: int = 5000) -> list[dict]:
        with self._lock:
            rs = self.conn.execute("SELECT * FROM events ORDER BY timestamp ASC LIMIT ?", (limit,)).fetchall()
        out=[]
        for r in rs:
            d=dict(r); d["attributes"] = json.loads(d.pop("attributes_json")); out.append(d)
        return out

    def update_session(self, event_id: str, session_id: str, trace_id: str | None = None) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE events SET session_id=?, trace_id=COALESCE(trace_id, ?) WHERE event_id=?",
                (session_id, trace_id, event_id),
            )
            self.conn.commit()

    def update_trace(self, event_id: str, trace_id: str, overwrite: bool = False) -> None:
        with self._lock:
            if overwrite:
                self.conn.execute("UPDATE events SET trace_id=? WHERE event_id=?", (trace_id, event_id))
            else:
                self.conn.execute("UPDATE events SET trace_id=COALESCE(trace_id, ?) WHERE event_id=?", (trace_id, event_id))
            self.conn.commit()
