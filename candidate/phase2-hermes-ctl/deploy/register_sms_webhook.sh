#!/usr/bin/env bash
# Register the Hermes CTL SMS webhook with the phone's forwarder app.
#
# For "SMS to URL Forwarder" (F-Droid: tech.bogomolov.incomingsmsgateway):
#   just open the app, add a rule:
#     - sender: *   (all senders)
#     - URL:    http://100.72.245.64:8089/webhook
#     - enable "Local network mode" (so it sends over Tailscale without public internet)
#   The app POSTs {"from":..,"text":..,"sentStamp":..,"receivedStamp":..,"sim":..}
#   to that URL. Retries automatically. No cert needed (Tailscale encrypts).
#
# For capcom6 SMS Gateway for Android (Local Server mode):
#   run from a host that can reach the phone's Local Server (laptop on same Wi-Fi):
#     curl -u <user>:<pass> -X POST -H "Content-Type: application/json" \
#       -d '{"url":"https://100.72.245.64:8089/webhook?source=capcom6","event":"sms:received"}' \
#       http://<phone-local-ip>:8080/webhooks
#
# This script is a helper only; the Bogomolov app is configured in its UI.
echo "SMS to URL Forwarder -> set webhook URL: http://100.72.245.64:8089/webhook (enable Local network mode)"
echo "capcom6 -> POST {url:'https://100.72.245.64:8089/webhook?source=capcom6',event:'sms:received'} to the phone's /webhooks"
