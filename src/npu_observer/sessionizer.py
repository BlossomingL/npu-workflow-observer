from __future__ import annotations
from collections import defaultdict
from datetime import datetime
import hashlib


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _fingerprint(e: dict) -> str:
    a=e.get("attributes", {})
    git=a.get("git", {}) if isinstance(a.get("git"), dict) else {}
    repo=git.get("repo_root") or e.get("cwd") or "unknown"
    branch=git.get("branch") or ""
    return f"{repo}|{branch}"


def assign_sessions(events: list[dict], gap_minutes: int=45) -> dict[str,str]:
    """Assign events to sessions while preserving coding-agent trace correlation.

    Native Cursor/Codex events carry their own conversation/session trace. ``link-agent``
    can attach shell/test/profile events to those traces. Once a trace is known to belong
    to a coding agent, every event carrying that trace is assigned to the same session.
    Remaining events use repo/branch + inactivity-gap sessionization.
    """
    groups=defaultdict(list)
    assigned: dict[str, str] = {}
    agent_traces: set[str] = set()

    for e in events:
        source=str(e.get("source") or "")
        if source.startswith("agent:"):
            trace=e.get("trace_id") or e.get("session_id")
            if trace:
                agent_traces.add(str(trace))

    for e in events:
        source=str(e.get("source") or "")
        trace=e.get("trace_id")
        native=e.get("session_id")
        if trace and str(trace) in agent_traces:
            assigned[e["event_id"]]=str(trace)
            continue
        if native and source.startswith("agent:"):
            assigned[e["event_id"]]=str(native)
            continue
        groups[_fingerprint(e)].append(e)

    for fp, es in groups.items():
        es.sort(key=lambda x:x["timestamp"])
        seq=0; last=None; sid=None
        for e in es:
            cur=_ts(e["timestamp"])
            if last is None or (cur-last).total_seconds() > gap_minutes*60:
                seq += 1
                short=hashlib.sha1(fp.encode()).hexdigest()[:8]
                sid=f"sess-{short}-{cur.strftime('%Y%m%d-%H%M%S')}-{seq}"
            assigned[e["event_id"]]=sid
            last=cur
    return assigned
