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
    groups=defaultdict(list)
    for e in events:
        groups[_fingerprint(e)].append(e)
    assigned={}
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
