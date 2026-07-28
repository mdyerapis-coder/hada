from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OutboxRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outbox_id: str
    queue_name: str
    message_kind: str
    payload: dict[str, Any]
    attempts: int = Field(ge=0)
    created_at: datetime
