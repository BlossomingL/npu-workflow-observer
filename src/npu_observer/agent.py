from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

from .git_utils import snapshot
from .redact import redact_text
from .schema import Event, now_iso

_SESSION_KEYS = (
    "conversation_id", "conversationId", "session_id", "sessionId",
    "thread_id", "threadId", "run_id", "runId", "task_id", "taskId", "id",
)
_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization)", re.I)
_UUID_AT_END = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")
_MAX_TEXT = 16_384


def _first(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _short_text(value: str, limit: int = _MAX_TEXT) -> str:
    value = redact_text(value)
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n<observer-truncated {len(value) - limit} chars>"


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return "<observer-max-depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                out[key] = "<redacted>"
            else:
                out[key] = _sanitize(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize(v, depth + 1) for v in value[:200]]
    if isinstance(value, str):
        return _short_text(value)
    return value


def _nested_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def agent_session_id(payload: dict[str, Any], fallback: str | None = None) -> str | None:
    """Find a native conversation/session id without recursively scanning arbitrary content."""
    for candidate in (
        payload,
        _nested_dict(payload, "payload"),
        _nested_dict(_nested_dict(payload, "payload"), "meta"),
        _nested_dict(payload, "meta"),
    ):
        value = _first(candidate, _SESSION_KEYS)
        if value is not None:
            return str(value)
    return fallback


def _cursor_fallback_session(cwd: str | None = None) -> tuple[str | None, str | None]:
    transcript = os.environ.get("CURSOR_TRANSCRIPT_PATH")
    if transcript:
        digest = hashlib.sha256(str(Path(transcript).expanduser()).encode()).hexdigest()[:24]
        return f"cursor-{digest}", transcript
    # Without a transcript or native session id, leave session_id unset. The generic
    # repo/branch + time-gap sessionizer is safer than incorrectly merging all chats.
    return None, None


def semantic_hook_name(provider: str, hook: str, payload: dict[str, Any]) -> str:
    text = hook.lower().replace("_", "").replace("-", "")
    payload_type = str(payload.get("type", "")).lower().replace("_", "").replace("-", "")
    combined = f"{text} {payload_type}"

    if "sessionstart" in combined or "taskstart" in combined:
        return "agent.task.started"
    if "sessionend" in combined:
        return "agent.session.completed"
    if "stop" in combined or "taskcomplete" in combined or "taskend" in combined:
        return "agent.task.completed"
    if "subagentstart" in combined:
        return "agent.subagent.started"
    if "subagentstop" in combined:
        return "agent.subagent.completed"
    if any(k in combined for k in ("beforesubmitprompt", "userprompt", "submitprompt", "promptsubmit")):
        return "agent.prompt.submitted"
    if "fileedit" in combined or "patch" in combined:
        return "agent.patch.applied"
    if "posttoolusefailure" in combined:
        return "agent.tool.failed"
    if any(k in combined for k in ("beforeshell", "pretool", "beforetool")):
        return "agent.tool.started"
    if any(k in combined for k in ("aftershell", "posttool", "aftertool")):
        return "agent.tool.completed"
    if "afteragentresponse" in combined or "agentresponse" in combined:
        return "agent.response.completed"
    if "afteragentthought" in combined or "agentthought" in combined:
        return "agent.thought.completed"
    return "agent.hook.observed"


def event_from_hook(provider: str, hook: str, payload: dict[str, Any], cwd: str | None = None) -> Event:
    clean = _sanitize(payload)
    effective_cwd = (
        cwd
        or clean.get("cwd")
        or clean.get("workspace_root")
        or clean.get("workspaceRoot")
        or (os.environ.get("CURSOR_PROJECT_DIR") if provider == "cursor" else None)
    )
    session = agent_session_id(clean)
    transcript = None
    if provider == "cursor" and not session:
        session, transcript = _cursor_fallback_session(str(effective_cwd) if effective_cwd else None)
    elif provider == "cursor":
        transcript = os.environ.get("CURSOR_TRANSCRIPT_PATH")

    event_name = semantic_hook_name(provider, hook, clean)

    # Do not persist model hidden reasoning/thought text. Cursor exposes an
    # afterAgentThought hook, but the observer stores only timing/metadata.
    if event_name == "agent.thought.completed":
        hook_payload: dict[str, Any] = {
            "duration_ms": clean.get("duration_ms"),
            "content_recorded": False,
        }
    else:
        hook_payload = clean

    attrs: dict[str, Any] = {
        "agent": {
            "provider": provider,
            "session_id": session,
            "hook": hook,
        },
        "hook_payload": hook_payload,
    }
    if provider == "cursor":
        attrs["agent"]["version"] = os.environ.get("CURSOR_VERSION")
        attrs["agent"]["transcript_path"] = transcript
        attrs["agent"]["remote"] = os.environ.get("CURSOR_CODE_REMOTE") == "true"
    if effective_cwd:
        include_diff = event_name in {"agent.patch.applied", "agent.task.completed", "agent.session.completed"}
        attrs["git"] = snapshot(str(effective_cwd), include_diff=include_diff)

    return Event(
        name=event_name,
        source=f"agent:{provider}",
        cwd=str(effective_cwd) if effective_cwd else None,
        trace_id=session,
        session_id=session,
        attributes=attrs,
    )


def _codex_meta(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return meta or payload


def codex_session_id(path: str | Path, row: dict[str, Any] | None = None) -> str:
    if row:
        found = agent_session_id(row)
        if found:
            return found
    match = _UUID_AT_END.search(Path(path).stem)
    if match:
        return match.group(1)
    return Path(path).stem


def _message_text(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if isinstance(message, str):
        return _short_text(message)
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        if parts:
            return _short_text("\n".join(parts))
    text = payload.get("text")
    return _short_text(text) if isinstance(text, str) else None


def _codex_semantic(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    outer = str(row.get("type", "unknown"))
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    inner = str(payload.get("type", ""))

    if outer == "session_meta":
        meta = _codex_meta(row)
        # Keep metadata only: base/system/developer instructions are not useful workflow evidence.
        detail = {k: meta.get(k) for k in (
            "id", "session_id", "cwd", "originator", "cli_version", "source",
            "thread_source", "model_provider", "model", "agent_nickname", "agent_role",
        ) if meta.get(k) is not None}
        return "agent.session.started", detail

    if outer == "event_msg":
        if inner == "task_started":
            return "agent.task.started", payload
        if inner == "task_complete":
            return "agent.task.completed", payload
        if inner == "user_message":
            return "agent.prompt.submitted", {"text": _message_text(payload)}
        if inner in {"agent_message", "assistant_message"}:
            return "agent.response.completed", {"text": _message_text(payload)}
        if inner == "token_count":
            return "agent.usage.updated", payload
        if inner == "item_completed":
            return "agent.item.completed", payload

    if outer == "response_item":
        if inner == "message":
            role = str(payload.get("role", ""))
            if role == "user":
                return "agent.prompt.record", {"role": role, "text": _message_text(payload)}
            if role == "assistant":
                return "agent.response.record", {"role": role, "text": _message_text(payload)}
        if inner in {"function_call", "custom_tool_call", "tool_call"}:
            detail = {
                "name": payload.get("name"),
                "call_id": payload.get("call_id") or payload.get("id"),
                "arguments": _sanitize(payload.get("arguments")),
            }
            return "agent.tool.started", detail
        if inner in {"function_call_output", "custom_tool_call_output", "tool_result"}:
            detail = {
                "name": payload.get("name"),
                "call_id": payload.get("call_id") or payload.get("id"),
                "output": _sanitize(payload.get("output") or payload.get("result")),
            }
            return "agent.tool.completed", detail
        if inner == "reasoning":
            return "agent.thought.completed", {"content_recorded": False}

    if outer == "turn_context":
        return "agent.iteration.started", {
            k: payload.get(k) for k in ("turn_id", "model", "cwd") if payload.get(k) is not None
        }
    if outer == "token_usage_record":
        return "agent.usage.updated", payload
    if outer in {"reasoning", "reasoning_item"}:
        return "agent.thought.completed", {"content_recorded": False}
    return "agent.session.record", {"outer_type": outer, "inner_type": inner}


def codex_events(path: str | Path, start_line: int = 0) -> list[Event]:
    path = Path(path).expanduser()
    result: list[Event] = []
    if not path.exists():
        return result

    session_id = codex_session_id(path)
    session_cwd: str | None = None
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue

            if row.get("type") == "session_meta":
                meta = _codex_meta(row)
                session_id = codex_session_id(path, row)
                cwd_value = meta.get("cwd")
                if cwd_value:
                    session_cwd = str(cwd_value)

            if line_no < start_line:
                continue

            name, detail = _codex_semantic(row)
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            cwd = payload.get("cwd") or payload.get("working_directory") or session_cwd or row.get("cwd")
            raw_id = f"{path.resolve()}:{line_no}:{line.rstrip()}".encode("utf-8", "replace")
            event_id = "codex-" + hashlib.sha256(raw_id).hexdigest()[:32]
            attrs: dict[str, Any] = {
                "agent": {
                    "provider": "codex",
                    "session_id": session_id,
                    "source_file": str(path),
                    "line": line_no,
                    "record_type": row.get("type"),
                },
                "record": _sanitize(detail),
            }
            if cwd:
                attrs["git"] = snapshot(str(cwd), include_diff=name in {"agent.task.completed"})
            result.append(Event(
                name=name,
                event_id=event_id,
                source="agent:codex",
                cwd=str(cwd) if cwd else None,
                trace_id=session_id,
                session_id=session_id,
                timestamp=str(row.get("timestamp") or row.get("time") or now_iso()),
                attributes=attrs,
            ))
    return result


def latest_codex_sessions(root: str | Path, limit: int = 20) -> list[Path]:
    root = Path(root).expanduser()
    if not root.exists():
        return []
    files = sorted(root.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def follow_codex(path: str | Path, poll_seconds: float = 1.0) -> Iterator[Event]:
    """Yield newly appended events from one Codex rollout JSONL file."""
    line_no = 0
    while True:
        events = codex_events(path, line_no)
        if events:
            line_no = max(int(e.attributes["agent"]["line"]) for e in events) + 1
            yield from events
        time.sleep(poll_seconds)


def follow_codex_root(root: str | Path, poll_seconds: float = 1.0) -> Iterator[Event]:
    """Follow all active/new Codex rollout files and discover new sessions automatically."""
    root = Path(root).expanduser()
    offsets: dict[str, int] = {}
    while True:
        for path in reversed(latest_codex_sessions(root, limit=100)):
            key = str(path.resolve())
            start = offsets.get(key, 0)
            events = codex_events(path, start)
            if events:
                offsets[key] = max(int(e.attributes["agent"]["line"]) for e in events) + 1
                yield from events
            elif key not in offsets:
                offsets[key] = 0
        time.sleep(poll_seconds)
