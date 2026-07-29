"""Communications commands: send (email / telegram outbound)."""

from __future__ import annotations

import argparse

from hermes_ctl.cli.store import _store
from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.email_channel import EmailChannel
from hermes_ctl.secrets import EnvSecretStore, SecretError, NetworkDenied, default_contact_policy


def build_parser(sub) -> None:
    ps = sub.add_parser("send", help="OUTBOUND message (gated: secrets + egress)")
    ssub = ps.add_subparsers(dest="send_channel", required=True)

    sem = ssub.add_parser("email")
    sem.add_argument("--to", required=True)
    sem.add_argument("--subject", default="(no subject)")
    sem.add_argument("--body", required=True)
    sem.set_defaults(func=_cmd_send)

    stg = ssub.add_parser("telegram")
    stg.add_argument("--to", required=True, help="chat id")
    stg.add_argument("--body", required=True)
    stg.set_defaults(func=_cmd_send)


def _cmd_send(args: argparse.Namespace) -> int:
    # Lazy import via cli module for test monkeypatch compatibility
    from hermes_ctl.cli import TelegramChannel

    secrets = EnvSecretStore()
    net = default_contact_policy()
    try:
        if args.send_channel == "email":
            net.require("smtps://smtp.gmail.com:465")
            user = secrets.get("GMAIL_SMTP_USER")
            pw = secrets.get("GMAIL_APP_PASSWORD")
            ch = EmailChannel(user=user, password=pw)
            msg = Message(channel="email", sender=user, recipient=args.to, subject=args.subject, body=args.body)
        elif args.send_channel == "telegram":
            net.require("https://api.telegram.org:443")
            token = secrets.get("TELEGRAM_BOT_TOKEN")
            ch = TelegramChannel(token=token)
            msg = Message(channel="telegram", sender="bot", recipient=args.to, body=args.body)
        else:  # pragma: no cover - argparse enforces choices
            print(f"unknown send channel: {args.send_channel}", file=__import__("sys").stderr)
            return 2
    except (SecretError, NetworkDenied) as exc:
        print(f"send blocked: {exc}", file=__import__("sys").stderr)
        return 1

    try:
        ref = ch.send(msg)
    except Exception as exc:  # noqa: BLE001 - surface the network failure clearly
        print(f"send failed: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"sent [{args.send_channel}] -> {args.to} (ref {ref})")
    return 0
