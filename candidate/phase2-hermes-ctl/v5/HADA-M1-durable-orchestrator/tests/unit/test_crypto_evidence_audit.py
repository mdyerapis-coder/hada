from pathlib import Path

import pytest

from hada.audit.chain import GENESIS_HASH, AuditChain, AuditVerificationError
from hada.canonical import canonical_json
from hada.crypto.signing import Ed25519Signer, Ed25519Verifier, SignatureError
from hada.evidence.store import EvidenceError, EvidenceStore


def test_canonical_json_is_deterministic() -> None:
    assert canonical_json({"b": 2, "a": [3, 1]}) == b'{"a":[3,1],"b":2}'


def test_ed25519_key_round_trip(tmp_path: Path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    signer = Ed25519Signer.generate()
    signer.save(private_key, public_key)
    loaded = Ed25519Signer.load(private_key)
    verifier = Ed25519Verifier.load(public_key)
    envelope = loaded.sign(b"governed evidence")
    verifier.verify(b"governed evidence", envelope)
    with pytest.raises(SignatureError):
        verifier.verify(b"tampered", envelope)
    assert oct(private_key.stat().st_mode & 0o777) == "0o600"


def test_evidence_store_detects_tampering(tmp_path: Path) -> None:
    signer = Ed25519Signer.generate()
    store = EvidenceStore(tmp_path / "evidence", signer)
    manifest = store.put_bytes(
        b"test evidence",
        logical_name="result.txt",
        media_type="text/plain",
    )
    object_path = store.verify(manifest, signer.verifier())
    object_path.chmod(0o640)
    object_path.write_bytes(b"tampered")
    with pytest.raises(EvidenceError):
        store.verify(manifest, signer.verifier())


def test_audit_chain_detects_payload_change() -> None:
    signer = Ed25519Signer.generate()
    chain = AuditChain(signer)
    first = chain.build(
        previous_hash=GENESIS_HASH,
        stream="milestone:M1",
        event_type="milestone.created",
        payload={"scope": ["orchestrator"]},
        actor_party=None,
    ).model_copy(update={"sequence": 1})
    second = chain.build(
        previous_hash=first.event_hash,
        stream="task:1",
        event_type="task.created",
        payload={"title": "durable state"},
        actor_party=1,
    ).model_copy(update={"sequence": 2})
    AuditChain.verify([first, second], signer.verifier())
    tampered = second.model_copy(update={"payload": {"title": "changed"}})
    with pytest.raises(AuditVerificationError):
        AuditChain.verify([first, tampered], signer.verifier())


def test_audit_sequence_gap_is_rejected() -> None:
    signer = Ed25519Signer.generate()
    record = AuditChain(signer).build(
        previous_hash=GENESIS_HASH,
        stream="system",
        event_type="started",
        payload={},
        actor_party=None,
    ).model_copy(update={"sequence": 2})
    with pytest.raises(AuditVerificationError):
        AuditChain.verify([record], signer.verifier())


def test_malformed_base64_signature_is_reported() -> None:
    signer = Ed25519Signer.generate()
    envelope = signer.sign(b"evidence").model_copy(update={"signature_b64": "!" * 88})
    with pytest.raises(SignatureError, match="verification failed"):
        signer.verifier().verify(b"evidence", envelope)


def test_evidence_store_rejects_existing_symlink(tmp_path: Path) -> None:
    import hashlib

    signer = Ed25519Signer.generate()
    store = EvidenceStore(tmp_path / "evidence", signer)
    data = b"symlink attack"
    digest = hashlib.sha256(data).hexdigest()
    object_path = store.root / "sha256" / digest[:2] / digest
    object_path.parent.mkdir(parents=True)
    target = tmp_path / "outside"
    target.write_bytes(data)
    object_path.symlink_to(target)
    with pytest.raises(EvidenceError, match="invalid"):
        store.put_bytes(data, logical_name="attack.bin")
