"""Hermes CTL — SMS webhook receiver (Phase 2).

Real-time inbound SMS: a phone app POSTs incoming SMS to this endpoint and we
persist it into the MemoryStore inbox. Two app formats are supported:

* capcom6 SMS Gateway for Android  -> {"event":"sms:received","payload":{...}}
* "SMS to URL Forwarder" (Bogomolov) -> {"from":..,"text":..,"sentStamp":..,..}
  (flat JSON; optional HMAC via X-Signature; plain HTTP, "Local network mode")

Stdlib-only (http.server). HMAC secret + listen host/port from env; never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from hermes_ctl.communications.channels import Message
from hermes_ctl.memory.store import MemoryStore


def verify_signature(secret_key: str, raw_body: bytes, timestamp: str, signature: str) -> bool:
    """HMAC-SHA256 over raw_body+timestamp (capcom6 scheme). Constant-time."""
    if not secret_key:
        return True  # unsigned mode (local/testing only)
    message = raw_body + timestamp.encode()
    expected = hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def payload_to_message(payload: dict, source: str = "capcom6") -> Message:
    """Convert a webhook payload to a Message.

    `source` selects the field mapping:
      * "capcom6" -> payload.message / payload.sender / payload.recipient / payload.messageId
      * "forwarder" (SMS to URL Forwarder) -> text / from / sim / receivedStamp
    """
    if source == "forwarder":
        return Message(
            channel="sms",
            sender=str(payload.get("from", "")),
            recipient="",
            body=str(payload.get("text", "")),
            id=str(payload.get("receivedStamp") or payload.get("sentStamp") or ""),
        )
    return Message(
        channel="sms",
        sender=str(payload.get("sender", "")),
        recipient=str(payload.get("recipient", "")),
        body=str(payload.get("message", "")),
        id=str(payload.get("messageId", "")),
    )


def handle_webhook(store: MemoryStore, raw_body: bytes, headers: dict, secret_key: str = "",
                   source: str = "auto") -> tuple[int, dict]:
    """Process a raw webhook POST. Returns (http_status, json_body).

    `source`: "auto" (detect), "capcom6", or "forwarder".
    """
    try:
        body = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        return 400, {"error": "invalid json"}
    ts = headers.get("X-Signature-Timestamp", "") or headers.get("Timestamp", "")
    sig = headers.get("X-Signature", "") or headers.get("Signature", "")
    if secret_key and not verify_signature(secret_key, raw_body, ts, sig):
        return 401, {"error": "bad signature"}

    # Detect payload format when auto.
    if source == "auto":
        if "event" in body:
            source = "capcom6"
        elif "text" in body or "from" in body:
            source = "forwarder"
        else:
            return 400, {"error": "unrecognized payload"}
    if source == "capcom6":
        payload = body.get("payload", {})
    else:
        payload = body
    msg = payload_to_message(payload, source=source)
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


def make_handler(store: MemoryStore, secret_key: str = "", source: str = "auto") -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, code: int, obj: dict) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(obj).encode())

        def _read_chunked(self) -> bytes:
            data = b""
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    continue
                try:
                    size = int(line.split(b";")[0], 16)
                except ValueError:
                    break
                if size == 0:
                    break
                data += self.rfile.read(size)
                self.rfile.read(2)  # trailing CRLF after chunk
            return data

        def do_POST(self) -> None:  # noqa: N802
            length = self.headers.get("Content-Length")
            te = (self.headers.get("Transfer-Encoding") or "").lower()
            if length:
                raw = self.rfile.read(int(length)) if int(length) else b"{}"
            elif "chunked" in te:
                raw = self._read_chunked() or b"{}"
            else:
                raw = b"{}"
            # allow ?source= override on the URL
            src = source
            if "source=forwarder" in (self.path or ""):
                src = "forwarder"
            elif "source=capcom6" in (self.path or ""):
                src = "capcom6"
            code, obj = handle_webhook(store, raw, dict(self.headers), secret_key, source=src)
            self._respond(code, obj)

        def log_message(self, format: str, *args: Any) -> None:  # silence default stderr logging
            pass

    return Handler


def serve(store: MemoryStore, host: str = "0.0.0.0", port: int = 8089, secret_key: str = "",
          source: str = "auto", tls: bool = False, cert: str = "", key: str = "") -> None:
    """Blocking serve. `tls=True` wraps the socket with the given cert/key."""
    handler = make_handler(store, secret_key, source)
    httpd = HTTPServer((host, port), handler)
    if tls:
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()


if __name__ == "__main__":
    secret = os.environ.get("SMS_WEBHOOK_SECRET", "")
    port = int(os.environ.get("SMS_WEBHOOK_PORT", "8089"))
    store = MemoryStore(persist_path=os.environ.get("MEMORY_STORE_PATH"))
    print(f"SMS webhook receiver on :{port} (secret={'set' if secret else 'none'})")
    serve(store, port=port, secret_key=secret)

