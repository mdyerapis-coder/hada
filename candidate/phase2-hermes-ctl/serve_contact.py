"""Hermes CTL — contact services launcher (TLS webhook receiver).

Serves the SMS `sms:received` webhook receiver over HTTPS on the tailnet IP so
the phone (capcom6 SMS Gateway, Local Server mode) can PUSH inbound SMS to this
host 24/7 without the laptop or any LAN dependency.

The phone reaches this over Tailscale (tailnet-routable). TLS is required by the
app for any non-localhost webhook; we use the self-signed cert in .certs/.

Run:  python3 serve_contact.py
Env:  SMS_WEBHOOK_SECRET (HMAC, optional), MEMORY_STORE_PATH (inbox persistence),
      CONTACT_HOST (default 0.0.0.0), CONTACT_PORT (default 8089),
      CONTACT_CERT / CONTACT_KEY (default .certs/webhook.crt/.key)
"""

from __future__ import annotations

import os
import ssl

from hermes_ctl.communications.webhook_receiver import make_handler, serve
from hermes_ctl.memory.store import MemoryStore


def main() -> None:
    host = os.environ.get("CONTACT_HOST", "0.0.0.0")
    port = int(os.environ.get("CONTACT_PORT", "8089"))
    cert = os.environ.get("CONTACT_CERT", os.path.join(os.path.dirname(__file__), ".certs", "webhook.crt"))
    key = os.environ.get("CONTACT_KEY", os.path.join(os.path.dirname(__file__), ".certs", "webhook.key"))
    secret = os.environ.get("SMS_WEBHOOK_SECRET", "")
    store_path = os.environ.get("MEMORY_STORE_PATH")
    store = MemoryStore(persist_path=store_path)

    if not (os.path.exists(cert) and os.path.exists(key)):
        raise SystemExit(f"Missing TLS cert/key: {cert} / {key}. Generate with openssl (see .certs/).")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)

    Handler = make_handler(store, secret_key=secret)

    # Wrap the stdlib HTTPServer with TLS.
    import http.server

    class SecureHTTPServer(http.server.HTTPServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.socket = context.wrap_socket(self.socket, server_side=True)

    print(f"[contact] HTTPS webhook receiver on https://{host}:{port} (secret={'set' if secret else 'none'})")
    httpd = SecureHTTPServer((host, port), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
