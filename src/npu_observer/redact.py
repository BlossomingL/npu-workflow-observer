from __future__ import annotations
import re

_PATTERNS = [
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)(--(?:password|token|api[-_]?key)(?:=|\s+))[^\s]+"),
    re.compile(r"(?i)((?:password|token|api[-_]?key|secret)\s*[=:]\s*)[^\s]+"),
]


def redact_text(text: str) -> str:
    out = text
    for p in _PATTERNS:
        out = p.sub(r"\1<REDACTED>", out)
    return out


def redact_env(env: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in env.items():
        ku = k.upper()
        if any(x in ku for x in ("TOKEN", "KEY", "PASSWORD", "SECRET", "AUTH")):
            out[k] = "<REDACTED>"
        else:
            out[k] = v
    return out
