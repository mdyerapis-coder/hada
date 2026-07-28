"""Hermes CTL — SMS transport via handset gateway (Phase 2, gated integration).

Implements the `Channel` seam for SMS where the **handset is the source of
truth**. An SMS-gateway app on the phone (e.g. an open-source Android SMS
gateway exposing a REST API) is polled over HTTP:

- `received()`  -> GET  {base}/messages   (reads SMS that arrived on the phone)
- `send()`      -> POST {base}/send        (asks the phone to send an SMS)

The gateway URL + bearer token are read from the environment at call time and
are NEVER stored on disk or in the repo (governance: no secrets persisted).

Reachability: the Hermes CTL host (hada box / laptop) must be able to reach the
phone. Recommend joining the phone to the same Tailscale tailnet as the server
so the gateway is reachable privately (e.g. http://<phone-tailscale-ip>:8080).

Tested offline by monkeypatching `_http_get` / `_http_post`.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from hermes_ctl.communications.channels import Channel, Message

# Default JSON field mapping for the gateway's messages list. Overridable per
# app via `field_map=` (some gateways use "from"/"body"/"date" etc.).
DEFAULT_FIELD_MAP = {
    "id": "id",
    "sender": "sender",
    "body": "text",
    "ts": "received",
}


class SmsChannel(Channel):
    """Polls a handset SMS-gateway REST API. Phone is the SMS owner."""

    name = "sms"

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        field_map: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url or os.environ.get("SMS_GATEWAY_URL")
        self._token = token or os.environ.get("SMS_GATEWAY_TOKEN")
        self._field_map = field_map or DEFAULT_FIELD_MAP

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _http_get(self, path: str) -> Any:
        if not self._base_url:
            raise RuntimeError("SMS_GATEWAY_URL not set (inject at runtime; never stored)")
        url = f"{self._base_url.rstrip('/')}{path}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def _http_post(self, path: str, payload: dict) -> Any:
        if not self._base_url:
            raise RuntimeError("SMS_GATEWAY_URL not set (inject at runtime; never stored)")
        url = f"{self._base_url.rstrip('/')}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def received(self, *, limit: int = 20) -> list[Message]:
        data = self._http_get("/messages") or []
        fm = self._field_map
        out: list[Message] = []
        for row in data[-limit:]:
            out.append(
                Message(
                    channel="sms",
                    sender=str(row.get(fm["sender"], "")),
                    recipient="self",
                    body=str(row.get(fm["body"], "")),
                    id=str(row.get(fm["id"], "")),
                )
            )
        return out

    def send(self, message: Message) -> str:
        payload = {"to": message.recipient, "text": message.body}
        self._http_post("/send", payload)
        return f"sms:{message.recipient}"
