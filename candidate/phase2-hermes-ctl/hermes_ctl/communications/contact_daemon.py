"""Hermes CTL — unified contact daemon (Telegram + Email + SMS inbound).

Single long-running service that funnels inbound messages from all three
transports into the MemoryStore inbox (tags: inbox, <channel>):

  * SMS      -> push webhook receiver (HTTP server on the tailnet IP)
  * Email    -> periodic IMAP poll (EmailChannel.received)
  * Telegram -> periodic getUpdates poll (TelegramChannel.received)

A channel is skipped (not crashed) if its credentials are absent from the
environment. Credentials are NEVER stored on disk beyond the gitignored
contact.env (which holds only env var names, no secret values committed).

Run:  python3 contact_daemon.py
Env:  see deploy/contact.env (gitignored). Key vars:
  MEMORY_STORE_PATH, CONTACT_HOST, CONTACT_PORT, CONTACT_TLS,
  GMAIL_SMTP_USER, GMAIL_APP_PASSWORD, TELEGRAM_BOT_TOKEN,
  CONTACT_POLL_SECONDS (default 30)
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

# Make the repo root importable when run directly (systemd ExecStart path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.email_channel import EmailChannel
from hermes_ctl.communications.telegram import TelegramChannel
from hermes_ctl.communications.webhook_receiver import serve as serve_sms
from hermes_ctl.memory.store import MemoryStore


def _store_inbox(store: MemoryStore, msg: Message, ref: str) -> None:
    store.remember(
        f"inbox:{msg.channel}:{ref}",
        {
            "channel": msg.channel,
            "sender": msg.sender,
            "recipient": msg.recipient,
            "subject": getattr(msg, "subject", "") or "",
            "body": msg.body,
            "ref": ref,
        },
        tags=("inbox", msg.channel),
    )


def _poll_loop(store: MemoryStore, name: str, fetch, interval: int, stop: threading.Event) -> None:
    """Generic periodic poll: fetch() -> list[Message]; store new ones."""
    seen: set[str] = set()
    while not stop.is_set():
        try:
            for msg in fetch():
                ref = msg.id or f"{name}:{msg.sender}:{hash(msg.body) & 0xffffffff:08x}"
                if ref in seen:
                    continue
                seen.add(ref)
                _store_inbox(store, msg, ref)
                print(f"[contact] {name} inbound from {msg.sender}: {msg.body[:40]!r}")
        except Exception as exc:  # network/creds issue -> skip this cycle
            print(f"[contact] {name} poll error (skipped): {exc}")
        stop.wait(interval)


def main() -> None:
    store = MemoryStore(persist_path=os.environ.get("MEMORY_STORE_PATH"))
    host = os.environ.get("CONTACT_HOST", "0.0.0.0")
    port = int(os.environ.get("CONTACT_PORT", "8089"))
    tls = os.environ.get("CONTACT_TLS", "off").lower() == "on"
    interval = int(os.environ.get("CONTACT_POLL_SECONDS", "30"))
    stop = threading.Event()

    threads: list[threading.Thread] = []

    # SMS: push webhook receiver (HTTP server in a background thread)
    def run_sms() -> None:
        if tls:
            cert = os.environ.get("CONTACT_CERT", os.path.join(os.path.dirname(__file__), ".certs", "webhook.crt"))
            key = os.environ.get("CONTACT_KEY", os.path.join(os.path.dirname(__file__), ".certs", "webhook.key"))
            serve_sms(store, host, port, tls=True, cert=cert, key=key)
        else:
            serve_sms(store, host, port)

    sms_t = threading.Thread(target=run_sms, name="sms-webhook", daemon=True)
    sms_t.start()
    threads.append(sms_t)
    print(f"[contact] SMS webhook receiver on :{port} (TLS={'on' if tls else 'off'})")

    # Email: periodic IMAP poll (only if creds present)
    if os.environ.get("GMAIL_SMTP_USER") and os.environ.get("GMAIL_APP_PASSWORD"):
        email_ch = EmailChannel()
        t = threading.Thread(
            target=_poll_loop,
            args=(store, "email", email_ch.received, interval, stop),
            name="email-poll", daemon=True,
        )
        t.start(); threads.append(t)
        print("[contact] Email inbound poll enabled")
    else:
        print("[contact] Email disabled (no GMAIL_SMTP_USER / GMAIL_APP_PASSWORD)")

    # Telegram: periodic getUpdates poll (only if token present)
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        tg_ch = TelegramChannel()
        t = threading.Thread(
            target=_poll_loop,
            args=(store, "telegram", tg_ch.received, interval, stop),
            name="telegram-poll", daemon=True,
        )
        t.start(); threads.append(t)
        print("[contact] Telegram inbound poll enabled")
    else:
        print("[contact] Telegram disabled (no TELEGRAM_BOT_TOKEN)")

    print(f"[contact] unified contact daemon running (poll every {interval}s)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
