from __future__ import annotations

import base64
import binascii
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field


class SignatureEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["ed25519"] = "ed25519"
    key_id: str = Field(min_length=16, max_length=64)
    signature_b64: str = Field(min_length=80, max_length=128)


class SignatureError(RuntimeError):
    pass


def _public_key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:32]


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


class Ed25519Signer:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self.key_id = _public_key_id(self._public_key)

    @classmethod
    def generate(cls) -> Ed25519Signer:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, path: Path, password: bytes | None = None) -> Ed25519Signer:
        if path.is_symlink():
            raise SignatureError("private key path may not be a symlink")
        data = path.read_bytes()
        key = serialization.load_pem_private_key(data, password=password)
        if not isinstance(key, Ed25519PrivateKey):
            raise SignatureError("private key is not Ed25519")
        return cls(key)

    def save(self, private_path: Path, public_path: Path, password: bytes | None = None) -> None:
        encryption: serialization.KeySerializationEncryption
        if password:
            encryption = serialization.BestAvailableEncryption(password)
        else:
            encryption = serialization.NoEncryption()
        private_data = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )
        public_data = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        _atomic_write(private_path, private_data, 0o600)
        _atomic_write(public_path, public_data, 0o644)

    def sign(self, data: bytes) -> SignatureEnvelope:
        signature = self._private_key.sign(data)
        return SignatureEnvelope(
            key_id=self.key_id,
            signature_b64=base64.b64encode(signature).decode("ascii"),
        )

    def verifier(self) -> Ed25519Verifier:
        return Ed25519Verifier(self._public_key)


class Ed25519Verifier:
    def __init__(self, public_key: Ed25519PublicKey) -> None:
        self._public_key = public_key
        self.key_id = _public_key_id(public_key)

    @classmethod
    def load(cls, path: Path) -> Ed25519Verifier:
        if path.is_symlink():
            raise SignatureError("public key path may not be a symlink")
        key = serialization.load_pem_public_key(path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise SignatureError("public key is not Ed25519")
        return cls(key)

    def verify(self, data: bytes, envelope: SignatureEnvelope) -> None:
        if envelope.algorithm != "ed25519":
            raise SignatureError(f"unsupported signature algorithm: {envelope.algorithm}")
        if envelope.key_id != self.key_id:
            raise SignatureError("signature key identifier does not match verifier")
        try:
            signature = base64.b64decode(envelope.signature_b64, validate=True)
            self._public_key.verify(signature, data)
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise SignatureError("signature verification failed") from exc
