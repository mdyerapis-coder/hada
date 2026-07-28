#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hada.canonical import canonical_json
from hada.crypto.signing import Ed25519Verifier, SignatureEnvelope
from hada.evidence.store import EvidenceManifest


def verify_bundle(bundle_root: Path) -> None:
    public_key = bundle_root / "evidence-signing-public.pem"
    index_path = bundle_root / "SIGNED-EVIDENCE-INDEX.json"
    verifier = Ed25519Verifier.load(public_key)
    index: dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
    signature = SignatureEnvelope.model_validate(index.pop("signature"))
    verifier.verify(canonical_json(index), signature)

    evidence_root = bundle_root / "evidence-store"
    for entry in index["entries"]:
        digest = str(entry["digest"])
        manifest_path = bundle_root / str(entry["manifest_path"])
        manifest = EvidenceManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if manifest.digest != digest:
            raise RuntimeError(f"index/manifest digest mismatch: {digest}")
        object_path = evidence_root / "sha256" / digest[:2] / digest
        if object_path.is_symlink() or not object_path.is_file():
            raise RuntimeError(f"missing evidence object: {digest}")
        data = object_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or len(data) != manifest.byte_size:
            raise RuntimeError(f"evidence object verification failed: {digest}")
        verifier.verify(canonical_json(manifest.unsigned_payload()), manifest.signature)
        expected_manifest = (
            Path("evidence-store")
            / "sha256"
            / digest[:2]
            / f"{digest}.manifest.json"
        )
        if Path(str(entry["manifest_path"])) != expected_manifest:
            raise RuntimeError(f"unexpected manifest path for {digest}")

    print(f"verified {len(index['entries'])} signed M1 evidence artifacts")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the HADA M1 evidence bundle")
    parser.add_argument(
        "bundle_root",
        nargs="?",
        type=Path,
        default=Path("artifacts/M1"),
    )
    args = parser.parse_args()
    verify_bundle(args.bundle_root.resolve())


if __name__ == "__main__":
    main()
