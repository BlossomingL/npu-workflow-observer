from __future__ import annotations
import argparse, json, socketserver
from .store import EventStore

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            try:
                event=json.loads(raw.decode("utf-8"))
                self.server.store.insert(event)  # type: ignore[attr-defined]
                self.wfile.write(b'{"ok":true}\n')
            except Exception as e:
                self.wfile.write((json.dumps({"ok":False,"error":str(e)})+"\n").encode())

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True


def run(db: str, host: str="127.0.0.1", port: int=43189):
    store=EventStore(db)
    with Server((host,port), Handler) as srv:
        srv.store=store  # type: ignore[attr-defined]
        print(f"npu-observerd listening on {host}:{port}, db={store.path}")
        srv.serve_forever()
