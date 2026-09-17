from __future__ import annotations
import subprocess
from pathlib import Path
from .redact import redact_text


def _run(args: list[str], cwd: str | None = None) -> str | None:
    try:
        p = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=3)
        if p.returncode == 0:
            return p.stdout.strip()
    except Exception:
        pass
    return None


def snapshot(cwd: str | None = None, include_diff: bool = True) -> dict:
    cwd = cwd or str(Path.cwd())
    root = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    if not root:
        return {}
    branch = _run(["git", "branch", "--show-current"], cwd)
    commit = _run(["git", "rev-parse", "HEAD"], cwd)
    status = _run(["git", "status", "--porcelain"], cwd) or ""
    out = {
        "repo_root": root,
        "branch": branch,
        "commit": commit,
        "dirty": bool(status.strip()),
        "changed_files": [line[3:] for line in status.splitlines() if len(line) > 3],
    }
    if include_diff:
        diff = _run(["git", "diff", "--no-ext-diff", "--unified=3"], cwd) or ""
        out["diff"] = redact_text(diff[:200_000])
    return out
