"""Hermes CTL — Telegram transport (Phase 2, gated integration).

Implements the `Channel` seam against the Telegram Bot API. The bot token is
read from the environment at call time and is NEVER stored on disk or in the
repo (governance: no secrets persisted). Stdlib-only (urllib).

Send/receive are real HTTP calls; tests monkeypatch `_post` so the module is
fully verifiable offline.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from hermes_ctl.communications.channels import Channel, Message


class TelegramChannel(Channel):
    """Bot API transport. `token` injected at runtime (env), not persisted."""

    name = "telegram"

    def __init__(self, token: str | None = None, *, api_base: str = "https://api.telegram.org") -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")

    def _get_token(self) -> str:
        tok = self._token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not tok:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set (inject at runtime; never stored)")
        return tok

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._api_base}/bot{self._get_token()}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # pragma: no cover - network path
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Telegram {method} failed: {e.code} {body}") from e

    def send(self, message: Message) -> str:
        # recipient is a chat id for Telegram
        result = self._post(
            "sendMessage",
            {"chat_id": message.recipient, "text": message.body},
        )
        if not result.get("ok"):  # pragma: no cover - network path
            raise RuntimeError(f"Telegram send failed: {result}")
        msg_id = str(result["result"]["message_id"])
        message.id = msg_id
        return msg_id

    def received(self) -> list[Message]:  # pragma: no cover - network path
        result = self._post("getUpdates", {})
        out: list[Message] = []
        for upd in result.get("result", []):
            msg = upd.get("message")
            if not msg:
                continue
            out.append(
                Message(
                    channel="telegram",
                    sender=str(msg.get("from", {}).get("id", "")),
                    recipient=str(msg.get("chat", {}).get("id", "")),
                    body=msg.get("text", ""),
                    id=str(msg.get("message_id", "")),
                )
            )
        return out
