#!/usr/bin/env python3
"""Send the HADA roadmaps to a Telegram chat, chunking long ones."""
import os, sys
from hermes_ctl.communications.telegram import TelegramChannel
from hermes_ctl.communications.channels import Message

CHAT = os.environ.get("TG_CHAT", "7620778176")
MAX = 3500

def chunks(text, size=MAX):
    parts, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > size and cur:
            parts.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        parts.append(cur)
    return parts

def send_file(path, label):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    parts = chunks(text)
    ch = TelegramChannel()
    header = f"📌 *{label}* ({len(parts)} part{'s' if len(parts)!=1 else ''})"
    ch.send(Message(channel="telegram", sender="bot", recipient=CHAT, body=header))
    for i, p in enumerate(parts, 1):
        body = p if len(parts) == 1 else f"--- {label} [{i}/{len(parts)}] ---\n{p}"
        ch.send(Message(channel="telegram", sender="bot", recipient=CHAT, body=body))
        print(f"sent {label} part {i}/{len(parts)} ({len(p)} chars)")

if __name__ == "__main__":
    base = sys.argv[1]
    send_file(os.path.join(base, "ROADMAP.md"), "HADA ROADMAP (M1)")
    send_file(os.path.join(base, "docs/MASTER_ROADMAP.md"), "HADA MASTER ROADMAP")
    print("ALL SENT")
