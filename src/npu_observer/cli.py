from __future__ import annotations
import argparse, json, os, subprocess, sys, time, uuid
from pathlib import Path
from .schema import Event
from .client import send_event
from .git_utils import snapshot
from .redact import redact_text
from .classify import classify_command
from .store import EventStore
from .sessionizer import assign_sessions
from .miner import mine, workflow_yaml
from .daemon import run as run_daemon
from .agent import event_from_hook, codex_events, latest_codex_sessions, follow_codex

DEFAULT_HOME=Path(os.environ.get("NPU_OBSERVER_HOME","~/.npu-observer")).expanduser()
DEFAULT_DB=str(DEFAULT_HOME/"observer.db")
DEFAULT_CODEX_SESSIONS=Path(os.environ.get("CODEX_HOME","~/.codex")).expanduser()/"sessions"

def emit(e: Event, offline_db: str|None=None):
    if e.cwd and "git" not in e.attributes:
        e.attributes["git"] = snapshot(e.cwd, include_diff=False)
    d=e.to_dict()
    if not send_event(d):
        EventStore(offline_db or DEFAULT_DB).insert(d)
    return d


def cmd_exec(args):
    cmd=args.command
    if cmd and cmd[0] == "--": cmd=cmd[1:]
    if not cmd:
        raise SystemExit("missing command")
    cmd_str=" ".join(cmd)
    cwd=os.getcwd()
    git=snapshot(cwd, include_diff=False)
    role=classify_command(cmd_str)
    span=str(uuid.uuid4())
    emit(Event(name="shell.command.started", kind="span_start", event_id=span, source="shell", cwd=cwd,
               attributes={"command":redact_text(cmd_str),"role":role,"git":git}), args.db)
    t=time.perf_counter()
    p=subprocess.run(cmd)
    dur=(time.perf_counter()-t)*1000
    emit(Event(name="shell.command.completed", kind="span_end", parent_id=span, source="shell", cwd=cwd,
               attributes={"command":redact_text(cmd_str),"role":role,"exit_code":p.returncode,"duration_ms":dur,"git":snapshot(cwd, include_diff=False)}), args.db)
    raise SystemExit(p.returncode)


def cmd_git(args):
    g=snapshot(args.cwd or os.getcwd(), include_diff=not args.no_diff)
    emit(Event(name="source.git.snapshot", source="git", cwd=args.cwd or os.getcwd(), attributes={"git":g}), args.db)
    print(json.dumps(g, ensure_ascii=False, indent=2))


def cmd_decision(args):
    attrs={"decision":args.message,"reason":args.reason or [],"evidence":args.evidence or []}
    emit(Event(name="decision.created", source="human", cwd=os.getcwd(), attributes=attrs), args.db)
    print("recorded decision")


def cmd_event(args):
    attrs=json.loads(args.attributes) if args.attributes else {}
    emit(Event(name=args.name, source=args.source, cwd=os.getcwd(), attributes=attrs), args.db)


def cmd_agent_hook(args):
    try:
        payload=json.load(sys.stdin)
    except json.JSONDecodeError:
        payload={"raw":sys.stdin.read()}
    if not isinstance(payload,dict): payload={"value":payload}
    event=event_from_hook(args.provider,args.hook,payload,args.cwd)
    emit(event,args.db)
    # Cursor command hooks communicate over stdio. Empty JSON means "observe only".
    print("{}")


def _resolve_codex_paths(args) -> list[Path]:
    if args.path:
        return [Path(args.path).expanduser()]
    return latest_codex_sessions(args.root,args.latest)


def cmd_import_codex(args):
    st=EventStore(args.db); count=0; paths=_resolve_codex_paths(args)
    for path in paths:
        for event in codex_events(path):
            st.insert(event.to_dict()); count += 1
    print(f"imported {count} records from {len(paths)} Codex session file(s)")


def cmd_watch_codex(args):
    paths=_resolve_codex_paths(args)
    if not paths:
        raise SystemExit(f"no Codex rollout JSONL found under {args.root}")
    path=paths[0]
    print(f"watching Codex session: {path}", file=sys.stderr)
    try:
        for event in follow_codex(path,args.poll):
            emit(event,args.db)
    except KeyboardInterrupt:
        pass


def cmd_sessionize(args):
    st=EventStore(args.db); es=st.rows(args.limit); assigned=assign_sessions(es,args.gap)
    for eid,sid in assigned.items(): st.update_session(eid,sid,trace_id=sid)
    print(f"assigned {len(assigned)} events into {len(set(assigned.values()))} sessions")


def cmd_mine(args):
    st=EventStore(args.db); model=mine(st.rows(args.limit),args.min_support)
    text=workflow_yaml(model,args.name)
    Path(args.output).write_text(text,encoding="utf-8")
    print(text)


def main():
    p=argparse.ArgumentParser(prog="npu-observer")
    p.add_argument("--db",default=DEFAULT_DB)
    sp=p.add_subparsers(dest="cmd",required=True)
    d=sp.add_parser("daemon"); d.add_argument("--host",default="127.0.0.1"); d.add_argument("--port",type=int,default=43189); d.set_defaults(func=lambda a:run_daemon(a.db,a.host,a.port))
    e=sp.add_parser("exec"); e.add_argument("command",nargs=argparse.REMAINDER); e.set_defaults(func=cmd_exec)
    g=sp.add_parser("git-snapshot"); g.add_argument("--cwd"); g.add_argument("--no-diff",action="store_true"); g.set_defaults(func=cmd_git)
    de=sp.add_parser("decision"); de.add_argument("-m","--message",required=True); de.add_argument("--reason",action="append"); de.add_argument("--evidence",action="append"); de.set_defaults(func=cmd_decision)
    ev=sp.add_parser("event"); ev.add_argument("name"); ev.add_argument("--source",default="manual"); ev.add_argument("--attributes"); ev.set_defaults(func=cmd_event)

    ah=sp.add_parser("agent-hook",help="receive a coding-agent hook payload on stdin")
    ah.add_argument("--provider",choices=["cursor","codex","generic"],required=True)
    ah.add_argument("--hook",required=True)
    ah.add_argument("--cwd")
    ah.set_defaults(func=cmd_agent_hook)

    ci=sp.add_parser("import-codex",help="import Codex rollout JSONL sessions")
    ci.add_argument("--path",help="one rollout-*.jsonl; otherwise scan --root")
    ci.add_argument("--root",default=str(DEFAULT_CODEX_SESSIONS))
    ci.add_argument("--latest",type=int,default=20)
    ci.set_defaults(func=cmd_import_codex)

    cw=sp.add_parser("watch-codex",help="follow the latest Codex rollout JSONL")
    cw.add_argument("--path")
    cw.add_argument("--root",default=str(DEFAULT_CODEX_SESSIONS))
    cw.add_argument("--latest",type=int,default=1)
    cw.add_argument("--poll",type=float,default=1.0)
    cw.set_defaults(func=cmd_watch_codex)

    s=sp.add_parser("sessionize"); s.add_argument("--gap",type=int,default=45); s.add_argument("--limit",type=int,default=100000); s.set_defaults(func=cmd_sessionize)
    m=sp.add_parser("mine"); m.add_argument("--limit",type=int,default=100000); m.add_argument("--min-support",type=float,default=.5); m.add_argument("--name",default="npu_observed_workflow"); m.add_argument("-o","--output",default="workflow.generated.yaml"); m.set_defaults(func=cmd_mine)
    a=p.parse_args(); a.func(a)

if __name__=="__main__": main()
