# Signing-Key Operations Runbook

## Initial generation

```bash
hada keys generate \
  --private-key /var/lib/hada/keys/audit-signing-key.pem \
  --public-key /var/lib/hada/keys/audit-signing-key.pub.pem
```

The private key must be mode `0600`, owned by the HADA service account and excluded from repositories, reports and evidence exports. Party 3 receives the public key only.

## Loss or suspected compromise

Stop HADA immediately. Preserve the current public key and final verified audit sequence. Do not overwrite the private-key path. A new key may be introduced only through a governance-approved rotation procedure that records both old and new key identifiers and is independently reviewed.

M1 intentionally does not automate rotation because an automated process on a compromised host cannot establish trustworthy continuity by itself.
