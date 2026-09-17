from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .git_utils import snapshot
from .redact import redact_text
from .schema import Event

_SESSION_KEYS = (
    "conversation_id", "conversationId", "session_id", "sessionId",
    "thread_id", "threadId", "run_id", "runId", "task_id", "taskId",
)

_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization)", re.I)


def _first(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                out[key] = "<redacted>"
            else:
                out[key] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def agent_session_id(payload: dict[str, Any], fallback: str | None = None) -> str | None:
    value = _first(payload, _SESSION_KEYS)
    if value is not None:
        return str(value)
    nested = payload.get("payload")
    if isinstance(nested, dict):
        value = _first(nested, _SESSION_KEYS)
        if value is not None:
            return str(value)
    return fallback


def semantic_hook_name(provider: str, hook: str, payload: dict[str, Any]) -> str:
    text = hook.lower().replace("_", "").replace("-", "")
    payload_type = str(payload.get("type", "")).lower().replace("_", "")
    combined = f"{text} {payload_type}"

    if "sessionstart" in combined or "taskstart" in combined:
        return "agent.task.started"
    if any(k in combined for k in ("sessionend", "taskend", "stop", "finish")):
        return "agent.task.completed"
    if any(k in combined for k in ("userprompt", "submitprompt", "promptsubmit")):
        return "agent.prompt.submitted"
    if "fileedit" in combined or "patch" in combined:
        return "agent.patch.applied"
    if any(k in combined for k in ("beforeshell", "pretool", "beforetool")):
        return "agent.tool.started"
    if any(k in combined for k in ("aftershell", "posttool", "aftertool")):
        return "agent.tool.completed"
    if any(k in combined for k in ("assistantmessage", "agentmessage", "messagecompleted")):
        return "agent.message.completed"
    return "agent.hook.observed"


def event_from_hook(provider: str, hook: str, payload: dict[str, Any], cwd: str | None = None) -> Event:
    clean = _sanitize(payload)
    session = agent_session_id(clean)
    event_name = semantic_hook_name(provider, hook, clean)
    effective_cwd = cwd or clean.get("cwd") or clean.get("workspace_root") or clean.get("workspaceRoot")

    attrs: dict[str, Any] = {
        "agent": {"provider": provider, "session_id": session, "hook": hook},
        "hook_payload": clean,
    }
    if effective_cwd:
        include_diff = event_name in {"agent.patch.applied", "agent.task.completed"}
        attrs["git"] = snapshot(str(effective_cwd), include_diff=include_diff)

    return Event(
        name=event_name,
        source=f"agent:{provider}",
        cwd=str(effective_cwd) if effective_cwd else None,
        trace_id=session,
        session_id=session,
        attributes=attrs,
    )


def codex_session_id(path: str | Path, row: dict[str, Any] | None = None) -> str:
    if row:
        found = agent_session_id(row)
        if found:
            return found
        payload = row.get("payload")
        if isinstance(payload, dict):
            found = agent_session_id(payload)
            if found:
                return found
    stem = Path(path).stem
    if stem.startswith("rollout-"):
        parts = stem.split("-")
        if len(parts) >= 2:
            return parts[-1]
    return stem


def _codex_semantic(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    outer = str(row.get("type", "unknown"))
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    inner = str(payload.get("type", ""))
    key = f"{outer}:{inner}".lower()

    if outer == "session_meta" or "session_meta" in key:
        return "agent.task.started", payload
    if "user_message" in key or inner in {"user", "input_text"}:
        return "agent.prompt.submitted", payload
    if "agent_message" in key or inner in {"assistant", "output_text"}:
        return "agent.message.completed", payload
    if any(x in key for x in ("function_call_output", "custom_tool_call_output", "tool_result")):
        return "agent.tool.completed", payload
    if any(x in key for x in ("function_call", "custom_tool_call", "tool_call")):
        return "agent.tool.started", payload
    if "turn_context" in key:
        return "agent.iteration.started", payload
    if "turn_aborted" in key or "turn_complete" in key or "task_complete" in key:
        return "agent.iteration.completed", payload
    return "agent.session.record", payload or row


def codex_events(path: str | Path, start_line: int = 0) -> list[Event]:
    path = Path(path).expanduser()
    result: list[Event] = []
    if not path.exists():
        return result

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f):
            if line_no < start_line or not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            name, detail = _codex_semantic(row)
            session = codex_session_id(path, row)
            raw_id = f"{path.resolve()}:{line_no}:{line.rstrip()}".encode("utf-8", "replace")
            event_id = "codex-" + hashlib.sha256(raw_id).hexdigest()[:32]
            cwd = None
            payload = row.get("payload")
            if isinstance(payload, dict):
                cwd = payload.get("cwd") or payload.get("working_directory")
            cwd = cwd or row.get("cwd")
            attrs: dict[str, Any] = {
                "agent": {
                    "provider": "codex",
                    "session_id": session,
                    "source_file": str(path),
                    "line": line_no,
                    "record_type": row.get("type"),
                },
                "record": _sanitize(detail),
            }
            if cwd:
                attrs["git"] = snapshot(str(cwd), include_diff=name in {"agent.task.completed", "agent.patch.applied"})
            result.append(Event(
                name=name,
                event_id=event_id,
                source="agent:codex",
                cwd=str(cwd) if cwd else None,
                trace_id=session,
                session_id=session,
                timestamp=str(row.get("timestamp") or row.get("time") or Event(name="x").timestamp),
                attributes=attrs,
            ))
    return result


def latest_codex_sessions(root: str | Path, limit: int = 20) -> list[Path]:
    root = Path(root).expanduser()
    if not root.exists():
        return []
    files = sorted(root.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def follow_codex(path: str | Path, poll_seconds: float = 1.0):
    """Yield newly appended events from one Codex rollout JSONL file."""
    line_no = 0
    while True:
        events = codex_events(path, line_no)
        if events:
            line_no = max(int(e.attributes["agent"]["line"]) for e in events) + 1
            for event in events:
                yield event
        time.sleep(poll_seconds)
