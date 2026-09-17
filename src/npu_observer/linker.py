from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _repo_key(event: dict[str, Any]) -> str:
    attrs = event.get("attributes") or {}
    git = attrs.get("git") if isinstance(attrs.get("git"), dict) else {}
    root = git.get("repo_root") or event.get("cwd") or "unknown"
    try:
        return str(Path(root).resolve())
    except Exception:
        return str(root)


def link_to_agent_traces(events: list[dict[str, Any]], window_minutes: int = 30) -> dict[str, str]:
    """Attach non-agent events to the closest active agent trace in the same repo.

    Only events without an existing trace are candidates. Once a non-agent event is
    linked, it advances the trace's last-seen timestamp, allowing a continuous build →
    test → profile chain to remain attached without requiring a fresh Agent event between
    every external tool invocation.
    """
    ordered = sorted(events, key=lambda x: x["timestamp"])
    active: dict[str, tuple[str, datetime]] = {}
    updates: dict[str, str] = {}

    for event in ordered:
        source = str(event.get("source") or "")
        repo = _repo_key(event)
        when = _ts(event["timestamp"])
        trace = event.get("trace_id") or event.get("session_id")

        if source.startswith("agent:") and trace:
            active[repo] = (str(trace), when)
            continue

        if event.get("trace_id"):
            continue
        current = active.get(repo)
        if not current:
            continue
        trace_id, last_seen = current
        delta=(when-last_seen).total_seconds()
        if 0 <= delta <= window_minutes * 60:
            updates[event["event_id"]] = trace_id
            active[repo] = (trace_id, when)

    return updates
