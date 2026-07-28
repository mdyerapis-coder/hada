#!/usr/bin/env python3
"""Reverse TCP forwarder so the loopback-only llmfit brains are reachable over
Tailscale by HADA peers (hada-control).

Listens on 0.0.0.0:<port> and forwards each connection to 127.0.0.1:<port>.
Stdlib-only, no deps. Run: python3 brain_forwarder.py
"""
import socket
import threading

BACKENDS = {
    8080: ("127.0.0.1", 8080),
    8081: ("127.0.0.1", 8081),
}

# Bind to the Tailscale IP (not 0.0.0.0) so we don't collide with the
# loopback-bound llmfit servers on 127.0.0.1:<port>. hada-control reaches us
# via this Tailscale address.
LISTEN_HOST = "100.72.245.64"


def relay(client: socket.socket, target_addr):
    try:
        upstream = socket.create_connection(target_addr, timeout=30)
    except OSError:
        client.close()
        return
    a, b = client, upstream

    def pump(x, y):
        try:
            while True:
                data = x.recv(65536)
                if not data:
                    break
                y.sendall(data)
        except OSError:
            pass
        finally:
            for s in (x, y):
                try:
                    s.close()
                except OSError:
                    pass

    t1 = threading.Thread(target=pump, args=(a, b), daemon=True)
    t2 = threading.Thread(target=pump, args=(b, a), daemon=True)
    t1.start()
    t2.start()


def serve(port: int):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, port))
    srv.listen(128)
    print(f"[forwarder] {LISTEN_HOST}:{port} -> 127.0.0.1:{port}")
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=relay, args=(conn, BACKENDS[port]), daemon=True).start()


if __name__ == "__main__":
    threads = [threading.Thread(target=serve, args=(p,), daemon=True) for p in BACKENDS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
