from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hada.canonical import canonical_json
from hada.crypto.signing import Ed25519Signer, Ed25519Verifier, SignatureEnvelope


class EvidenceError(RuntimeError):
    pass


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm: str = "sha256"
    media_type: str
    byte_size: int = Field(ge=0)
    created_at: datetime
    logical_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    signature: SignatureEnvelope

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "algorithm": self.algorithm,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "created_at": self.created_at,
            "logical_name": self.logical_name,
            "metadata": self.metadata,
        }


class EvidenceStore:
    def __init__(self, root: Path, signer: Ed25519Signer) -> None:
        self.root = root.resolve()
        self.signer = signer
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)

    def _object_path(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / digest

    def _manifest_path(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / f"{digest}.manifest.json"

    @staticmethod
    def _atomic_write(path: Path, data: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def put_bytes(
        self,
        data: bytes,
        *,
        logical_name: str,
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceManifest:
        digest = hashlib.sha256(data).hexdigest()
        object_path = self._object_path(digest)
        manifest_path = self._manifest_path(digest)

        if object_path.is_symlink():
            raise EvidenceError(f"existing evidence object is invalid: {digest}")
        if object_path.exists():
            if not object_path.is_file():
                raise EvidenceError(f"existing evidence object is invalid: {digest}")
            existing_digest = hashlib.sha256(object_path.read_bytes()).hexdigest()
            if existing_digest != digest:
                raise EvidenceError(f"existing evidence object is invalid: {digest}")
        else:
            self._atomic_write(object_path, data, 0o440)

        unsigned = {
            "digest": digest,
            "algorithm": "sha256",
            "media_type": media_type,
            "byte_size": len(data),
            "created_at": datetime.now(UTC),
            "logical_name": logical_name,
            "metadata": metadata or {},
        }
        manifest = EvidenceManifest(
            **unsigned,
            signature=self.signer.sign(canonical_json(unsigned)),
        )
        encoded = canonical_json(manifest) + b"\n"

        if manifest_path.exists():
            existing = EvidenceManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            self.verify(existing, self.signer.verifier())
            return existing

        self._atomic_write(manifest_path, encoded, 0o440)
        return manifest

    def put_file(
        self,
        source: Path,
        *,
        logical_name: str | None = None,
        media_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceManifest:
        if source.is_symlink() or not source.is_file():
            raise EvidenceError("evidence source must be a regular file")
        return self.put_bytes(
            source.read_bytes(),
            logical_name=logical_name or source.name,
            media_type=media_type,
            metadata=metadata,
        )

    def load_manifest(self, digest: str) -> EvidenceManifest:
        path = self._manifest_path(digest)
        if path.is_symlink() or not path.is_file():
            raise EvidenceError(f"manifest not found: {digest}")
        return EvidenceManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def verify(self, manifest: EvidenceManifest, verifier: Ed25519Verifier) -> Path:
        object_path = self._object_path(manifest.digest)
        if object_path.is_symlink() or not object_path.is_file():
            raise EvidenceError(f"evidence object not found: {manifest.digest}")
        data = object_path.read_bytes()
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != manifest.digest or len(data) != manifest.byte_size:
            raise EvidenceError("evidence content hash or size mismatch")
        verifier.verify(canonical_json(manifest.unsigned_payload()), manifest.signature)
        return object_path

    def export_manifest(self, manifest: EvidenceManifest, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
