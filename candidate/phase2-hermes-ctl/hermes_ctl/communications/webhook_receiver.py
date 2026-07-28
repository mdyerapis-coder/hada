"""Hermes CTL — SMS webhook receiver (capcom6 sms:received) (Phase 2).

Real-time inbound SMS: the phone app POSTs `sms:received` webhooks to this
endpoint. We validate the HMAC signature (if a secret is configured), convert
the payload to a `Message`, and persist it into the `MemoryStore` inbox.

Stdlib-only (http.server). Designed to be mounted in the Hermes CTL service.
HMAC secret + listen host/port from env; never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

from hermes_ctl.communications.channels import Message
from hermes_ctl.memory.store import MemoryStore


def verify_signature(secret_key: str, raw_body: bytes, timestamp: str, signature: str) -> bool:
    """HMAC-SHA256 over raw_body+timestamp (capcom6 scheme). Constant-time."""
    if not secret_key:
        return True  # unsigned mode (local/testing only)
    message = raw_body + timestamp.encode()
    expected = hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def payload_to_message(payload: dict) -> Message:
    """Convert an sms:received webhook payload to a Message."""
    return Message(
        channel="sms",
        sender=str(payload.get("sender", "")),
        recipient=str(payload.get("recipient", "")),
        body=str(payload.get("message", "")),
        id=str(payload.get("messageId", "")),
    )


def handle_webhook(store: MemoryStore, raw_body: bytes, headers: dict, secret_key: str = "") -> tuple[int, dict]:
    """Process a raw webhook POST. Returns (http_status, json_body)."""
    try:
        body = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        return 400, {"error": "invalid json"}
    ts = headers.get("X-Signature-Timestamp", "") or headers.get("Timestamp", "")
    sig = headers.get("X-Signature", "") or headers.get("Signature", "")
    if secret_key and not verify_signature(secret_key, raw_body, ts, sig):
        return 401, {"error": "bad signature"}
    event = body.get("event")
    if event == "sms:received":
        msg = payload_to_message(body.get("payload", {}))
        store.remember(
            f"inbox:{msg.channel}:{msg.id}",
            {
                "channel": msg.channel,
                "sender": msg.sender,
                "recipient": msg.recipient,
                "body": msg.body,
                "ref": msg.id,
            },
            tags=("inbox", "sms"),
        )
        return 200, {"ok": True}
    return 200, {"ok": True, "ignored": event}


def make_handler(store: MemoryStore, secret_key: str = "") -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, code: int, obj: dict) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode())

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            code, obj = handle_webhook(store, raw, dict(self.headers), secret_key)
            self._respond(code, obj)

        def log_message(self, format: str, *args: Any) -> None:  # silence default stderr logging
            pass

    return Handler


def serve(store: MemoryStore, host: str = "0.0.0.0", port: int = 8089, secret_key: str = "") -> None:
    """Blocking serve. In production mount under the Hermes CTL service instead."""
    httpd = HTTPServer((host, port), make_handler(store, secret_key))
    httpd.serve_forever()


if __name__ == "__main__":
    import sys

    secret = os.environ.get("SMS_WEBHOOK_SECRET", "")
    port = int(os.environ.get("SMS_WEBHOOK_PORT", "8089"))
    store = MemoryStore(persist_path=os.environ.get("MEMORY_STORE_PATH"))
    print(f"SMS webhook receiver on :{port} (secret={'set' if secret else 'none'})")
    serve(store, port=port, secret_key=secret)
