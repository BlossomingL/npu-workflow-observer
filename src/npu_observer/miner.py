from __future__ import annotations
from collections import Counter, defaultdict
import json

IGNORE={"shell.command.started","source.git.snapshot"}

def _semantic_name(e: dict) -> str:
    a=e.get("attributes",{})
    if e["name"] == "shell.command.completed":
        role=a.get("role")
        if role: return role
    return e["name"]


def mine(events: list[dict], min_support: float=0.5) -> dict:
    sessions=defaultdict(list)
    for e in events:
        if e.get("session_id"):
            sessions[e["session_id"]].append(e)
    seqs=[]
    for _, es in sessions.items():
        es.sort(key=lambda x:x["timestamp"])
        seq=[]
        for e in es:
            n=_semantic_name(e)
            if n in IGNORE: continue
            if not seq or seq[-1]!=n:
                seq.append(n)
        if seq: seqs.append(seq)
    step_count=Counter(x for seq in seqs for x in set(seq))
    trans=Counter()
    for seq in seqs:
        trans.update(zip(seq,seq[1:]))
    n=max(len(seqs),1)
    core=[s for s,c in step_count.most_common() if c/n >= min_support]
    edges=[{"from":a,"to":b,"count":c} for (a,b),c in trans.most_common()]
    return {"sessions":len(seqs),"core_steps":core,"transitions":edges}


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def workflow_yaml(model: dict, name: str="npu_observed_workflow") -> str:
    lines=[
        f"name: {_q(name)}",
        "version: 1",
        f"generated_from_sessions: {model.get('sessions',0)}",
        "steps:",
    ]
    for s in model.get("core_steps",[]):
        key=s.replace('.', '_')
        lines += [
            f"  - {key}:",
            "      tool: TODO",
            "      observed: true",
        ]
    lines += ["evidence:", "  transitions:"]
    for t in model.get("transitions",[])[:20]:
        lines += [
            f"    - from: {_q(t['from'])}",
            f"      to: {_q(t['to'])}",
            f"      count: {int(t['count'])}",
        ]
    return "\n".join(lines)+"\n"
