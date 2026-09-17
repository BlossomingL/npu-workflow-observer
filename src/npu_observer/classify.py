from __future__ import annotations
import shlex

def classify_command(cmd: str) -> str | None:
    c=cmd.lower()
    if any(x in c for x in ("cmake --build","make ","ninja","build.sh","compile")): return "build"
    if any(x in c for x in ("pytest","run_test","test.sh","ut_test")): return "test"
    if any(x in c for x in ("benchmark","bench.py","perf_test")): return "benchmark"
    if any(x in c for x in ("msprof","nsys","ncu","profiler")): return "profile"
    if c.startswith("ssh ") or " ssh " in c: return "remote"
    return None
