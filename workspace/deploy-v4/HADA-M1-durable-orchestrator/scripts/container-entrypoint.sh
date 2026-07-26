#!/usr/bin/env sh
set -eu

private_key=/var/lib/hada/keys/audit-signing-key.pem
public_key=/var/lib/hada/keys/audit-signing-key.pub.pem
mkdir -p /var/lib/hada/keys /var/lib/hada/evidence /var/lib/hada/workspaces
chmod 700 /var/lib/hada/keys

if [ ! -f "$private_key" ] || [ ! -f "$public_key" ]; then
  hada keys generate --private-key "$private_key" --public-key "$public_key"
fi

hada db migrate --config "${HADA_CONFIG:-/opt/hada/config/hada.yaml}"
exec "$@"
