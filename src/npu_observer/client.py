from __future__ import annotations
import json, socket

DEFAULT_HOST="127.0.0.1"
DEFAULT_PORT=43189

def send_event(event: dict, host: str=DEFAULT_HOST, port: int=DEFAULT_PORT, timeout: float=0.5) -> bool:
    data=(json.dumps(event, ensure_ascii=False)+"\n").encode()
    try:
        with socket.create_connection((host,port), timeout=timeout) as s:
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
            ack=s.recv(4096)
            return b'"ok": true' in ack or b'"ok":true' in ack
        return False
    except OSError:
        return False
