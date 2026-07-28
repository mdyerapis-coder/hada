"""Hermes CTL — contact services launcher (SMS webhook receiver).

Serves the inbound-SMS webhook receiver so a phone app can PUSH incoming SMS to
this host 24/7 without the laptop or any LAN dependency.

Two transport modes (env CONTACT_TLS):
  * "off" (default): plain HTTP on the tailnet IP. Safe because Tailscale already
    encrypts at the WireGuard layer; the phone app's "Local network mode" reaches
    it without a public IP or cert hassle.
  * "on": HTTPS with the self-signed cert in .certs/ (for non-Tailscale callers).

Phone side (pick one app):
  * "SMS to URL Forwarder" (F-Droid tech.bogomolov.incomingsmsgateway) -> set webhook
    URL http://<tailnet-ip>:8089/webhook , enable "Local network mode".
  * capcom6 SMS Gateway -> POST sms:received to https://<tailnet-ip>:8089/webhook .

Run:  python3 serve_contact.py
Env:  SMS_WEBHOOK_SECRET (HMAC, optional), MEMORY_STORE_PATH (inbox persistence),
      CONTACT_HOST (0.0.0.0), CONTACT_PORT (8089), CONTACT_TLS (off|on),
      CONTACT_CERT / CONTACT_KEY (.certs/webhook.crt/.key when TLS on),
      CONTACT_SOURCE (auto|capcom6|forwarder)
"""

from __future__ import annotations

import os

from hermes_ctl.communications.webhook_receiver import serve
from hermes_ctl.memory.store import MemoryStore


def main() -> None:
    host = os.environ.get("CONTACT_HOST", "0.0.0.0")
    port = int(os.environ.get("CONTACT_PORT", "8089"))
    tls = os.environ.get("CONTACT_TLS", "off").lower() == "on"
    secret = os.environ.get("SMS_WEBHOOK_SECRET", "")
    source = os.environ.get("CONTACT_SOURCE", "auto")
    store_path = os.environ.get("MEMORY_STORE_PATH")
    store = MemoryStore(persist_path=store_path)

    if tls:
        cert = os.environ.get("CONTACT_CERT", os.path.join(os.path.dirname(__file__), ".certs", "webhook.crt"))
        key = os.environ.get("CONTACT_KEY", os.path.join(os.path.dirname(__file__), ".certs", "webhook.key"))
        if not (os.path.exists(cert) and os.path.exists(key)):
            raise SystemExit(f"Missing TLS cert/key: {cert} / {key}.")
        print(f"[contact] HTTPS webhook receiver on :{port} (secret={'set' if secret else 'none'}, source={source})")
        serve(store, host, port, secret_key=secret, source=source, tls=True, cert=cert, key=key)
    else:
        print(f"[contact] HTTP webhook receiver on :{port} (Tailscale-encrypted; secret={'set' if secret else 'none'}, source={source})")
        serve(store, host, port, secret_key=secret, source=source, tls=False)


if __name__ == "__main__":
    main()
