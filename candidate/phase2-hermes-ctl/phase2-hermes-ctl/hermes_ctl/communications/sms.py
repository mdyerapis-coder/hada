"""Hermes CTL — SMS transport via capcom6 SMS Gateway for Android (Phase 2).

Implements the `Channel` seam against the app's **Local Server** mode, where
the phone itself runs the API (no cloud, no extra container). Verified against
the real API (docs.sms-gate.app):

- Send:    POST /message   body {"textMessage":{"text":...},"phoneNumbers":[..]}
- Receive (poll): GET /inbox?type=SMS&limit=N  -> [{id,sender,recipient,
                                                      contentPreview,createdAt}]
- Real-time: the app also pushes `sms:received` webhooks; see webhook_receiver.py.

Auth: HTTP **Basic** (username:password) from env. Credentials are NEVER stored
on disk or in the repo (governance). Tested offline by monkeypatching the HTTP
helpers.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Any

from hermes_ctl.communications.channels import Channel, Message


class SmsChannel(Channel):
    """Local-Server SMS gateway (capcom6 app) on the handset. Phone owns SMS."""

    name = "sms"

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("SMS_GATEWAY_URL", "")).rstrip("/")
        self._username = username or os.environ.get("SMS_GATEWAY_USER")
        self._password = password or os.environ.get("SMS_GATEWAY_PASS")

    def _auth_header(self) -> str:
        if not self._username or not self._password:
            raise RuntimeError("SMS_GATEWAY_USER / SMS_GATEWAY_PASS not set (inject at runtime; never stored)")
        raw = f"{self._username}:{self._password}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _http(self, method: str, path: str, payload: dict | None = None) -> Any:
        if not self._base_url:
            raise RuntimeError("SMS_GATEWAY_URL not set (inject at runtime; never stored)")
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": self._auth_header()}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode()
            return json.loads(body) if body else None

    def send(self, message: Message) -> str:
        self._http(
            "POST",
            "/message",
            {"textMessage": {"text": message.body}, "phoneNumbers": [message.recipient]},
        )
        return f"sms:{message.recipient}"

    def received(self, *, limit: int = 20) -> list[Message]:
        data = self._http("GET", f"/inbox?type=SMS&limit={limit}") or []
        out: list[Message] = []
        for row in data:
            out.append(
                Message(
                    channel="sms",
                    sender=str(row.get("sender", "")),
                    recipient=str(row.get("recipient", "")),
                    body=str(row.get("contentPreview", "")),
                    id=str(row.get("id", "")),
                )
            )
        return out
