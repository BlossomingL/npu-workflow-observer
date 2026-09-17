from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 只安装观察型 hook。避免 preToolUse/beforeReadFile 等权限型 hook，
# 降低 Observer 因输出格式错误而阻塞 Cursor Agent 的风险。
CURSOR_OBSERVER_HOOKS = (
    "sessionStart",
    "sessionEnd",
    "beforeSubmitPrompt",
    "afterShellExecution",
    "afterFileEdit",
    "postToolUseFailure",
    "afterAgentResponse",
    "afterAgentThought",
    "stop",
)


def hook_command(hook: str) -> str:
    return f"npu-observer agent-hook --provider cursor --hook {hook}"


def expected_hook_response(hook: str) -> dict[str, Any]:
    """Return a Cursor-compatible non-blocking response for observer hooks."""
    if hook == "beforeSubmitPrompt":
        return {"continue": True}
    return {}


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "hooks": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Cursor hooks config must be an object: {path}")
    data.setdefault("version", 1)
    data.setdefault("hooks", {})
    if not isinstance(data["hooks"], dict):
        raise ValueError(f"Cursor hooks field must be an object: {path}")
    return data


def install_cursor_hooks(path: str | Path) -> tuple[Path, int]:
    """Merge observer commands into an existing Cursor hooks.json idempotently."""
    path = Path(path).expanduser()
    cfg = _load(path)
    added = 0
    for hook in CURSOR_OBSERVER_HOOKS:
        entries = cfg["hooks"].setdefault(hook, [])
        if not isinstance(entries, list):
            raise ValueError(f"Cursor hook {hook} must be a list")
        command = hook_command(hook)
        if not any(isinstance(x, dict) and x.get("command") == command for x in entries):
            entries.append({"command": command, "timeout": 10})
            added += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, added


def default_cursor_hooks_path(scope: str, project_dir: str | None = None) -> Path:
    if scope == "user":
        return Path("~/.cursor/hooks.json").expanduser()
    if scope == "project":
        root = Path(project_dir or os.getcwd()).expanduser().resolve()
        return root / ".cursor" / "hooks.json"
    raise ValueError(f"unsupported Cursor hook scope: {scope}")
