from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from hada.canonical import canonical_json
from hada.crypto.signing import Ed25519Signer, Ed25519Verifier, SignatureEnvelope

GENESIS_HASH = "0" * 64


class AuditVerificationError(RuntimeError):
    pass


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int | None = Field(default=None, ge=1)
    event_id: str
    stream: str
    event_type: str
    actor_party: int | None = Field(default=None, ge=1, le=3)
    occurred_at: datetime
    payload: dict[str, Any]
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: SignatureEnvelope

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stream": self.stream,
            "event_type": self.event_type,
            "actor_party": self.actor_party,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
        }


class AuditChain:
    def __init__(self, signer: Ed25519Signer) -> None:
        self.signer = signer

    def build(
        self,
        *,
        previous_hash: str,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        actor_party: int | None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> AuditRecord:
        timestamp = occurred_at or datetime.now(UTC)
        unsigned = {
            "event_id": event_id or str(uuid4()),
            "stream": stream,
            "event_type": event_type,
            "actor_party": actor_party,
            "occurred_at": timestamp,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        event_hash = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return AuditRecord(
            **unsigned,
            event_hash=event_hash,
            signature=self.signer.sign(bytes.fromhex(event_hash)),
        )

    @staticmethod
    def verify(records: Iterable[AuditRecord], verifier: Ed25519Verifier) -> None:
        previous = GENESIS_HASH
        expected_sequence = 1
        for record in records:
            if record.sequence is not None and record.sequence != expected_sequence:
                raise AuditVerificationError(
                    f"audit sequence gap: expected {expected_sequence}, got {record.sequence}"
                )
            if record.previous_hash != previous:
                raise AuditVerificationError("audit hash chain is broken")
            expected_hash = hashlib.sha256(canonical_json(record.unsigned_payload())).hexdigest()
            if expected_hash != record.event_hash:
                raise AuditVerificationError("audit event hash mismatch")
            try:
                verifier.verify(bytes.fromhex(record.event_hash), record.signature)
            except Exception as exc:
                raise AuditVerificationError("audit signature verification failed") from exc
            previous = record.event_hash
            expected_sequence += 1
