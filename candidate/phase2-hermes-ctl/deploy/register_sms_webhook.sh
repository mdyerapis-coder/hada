#!/usr/bin/env bash
# Register the Hermes CTL SMS webhook with the capcom6 app on the phone.
#
# The phone's Local Server API is only reachable on the phone's LAN (or via the
# phone itself). Run this from a host that can reach the phone's Local Server
# URL (the laptop on the same Wi-Fi, or a shell on the phone). It tells the app
# to PUSH `sms:received` to the Hermes CTL receiver on hada-control over Tailscale.
#
# Args:
#   $1  phone Local Server base URL  (e.g. http://192.0.0.2:8080)
#   $2  phone Local Server username  (from app Settings > Local Server)
#   $3  phone Local Server password
#   $4  (optional) Hermes CTL receiver URL  (default https://100.77.108.35:8089/webhook)
set -euo pipefail

PHONE_URL="${1:?usage: register_sms_webhook.sh <phone_local_url> <user> <pass> [receiver_url]}"
USER="${2:?}"
PASS="${3:?}"
RECEIVER_URL="${4:-https://100.72.245.64:8089/webhook}"

echo "Registering sms:received -> $RECEIVER_URL on $PHONE_URL"
curl -s -u "$USER:$PASS" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$RECEIVER_URL\",\"event\":\"sms:received\"}" \
  "$PHONE_URL/webhooks"
echo
echo "Done. Send an SMS to the phone; it should arrive in the Hermes CTL inbox."
