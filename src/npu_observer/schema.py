from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any
import json, os, socket, uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


@dataclass
class Event:
    name: str
    kind: str = "event"  # event|span_start|span_end
    timestamp: str = field(default_factory=now_iso)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str | None = None
    session_id: str | None = None
    parent_id: str | None = None
    cwd: str | None = None
    source: str = "cli"
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["host"] = socket.gethostname()
        d["pid"] = os.getpid()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
