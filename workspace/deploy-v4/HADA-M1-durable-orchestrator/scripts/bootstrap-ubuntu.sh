#!/usr/bin/env bash
# shellcheck disable=SC1091
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

source /etc/os-release
if [[ ${ID} != ubuntu || ${VERSION_ID} != "24.04" ]]; then
  echo "HADA requires Ubuntu 24.04 LTS; found ${PRETTY_NAME}" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  bubblewrap ca-certificates curl git gnupg jq python3 python3-pip python3-venv \
  rsync uidmap unattended-upgrades

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
cat >/etc/apt/sources.list.d/docker.sources <<DOCKER
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Signed-By: /etc/apt/keyrings/docker.gpg
DOCKER
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if ! getent group hada >/dev/null 2>&1; then
  groupadd --system --gid 10001 hada
fi
if ! id hada >/dev/null 2>&1; then
  useradd --system --uid 10001 --gid hada --create-home \
    --home-dir /var/lib/hada --shell /usr/sbin/nologin hada
fi
if [[ $(id -u hada) -ne 10001 || $(id -g hada) -ne 10001 ]]; then
  echo "Existing hada account must use UID/GID 10001 for container volume ownership" >&2
  exit 1
fi
usermod -aG docker hada

install -d -o root -g hada -m 0750 /opt/hada
install -d -o hada -g hada -m 0750 \
  /var/lib/hada /var/lib/hada/evidence /var/lib/hada/keys \
  /var/lib/hada/repositories /var/lib/hada/workspaces /var/log/hada
rsync -a --delete --exclude '.git' --exclude '.env' ./ /opt/hada/
chown -R root:hada /opt/hada
find /opt/hada -type d -exec chmod g-w,o-rwx {} +

python3 -m venv /opt/hada/.venv
/opt/hada/.venv/bin/pip install --upgrade pip
/opt/hada/.venv/bin/pip install /opt/hada

if [[ ! -f /var/lib/hada/keys/audit-signing-key.pem ]]; then
  runuser -u hada -- /opt/hada/.venv/bin/hada keys generate \
    --private-key /var/lib/hada/keys/audit-signing-key.pem \
    --public-key /var/lib/hada/keys/audit-signing-key.pub.pem
fi

install -m 0644 /opt/hada/scripts/hada-supervisor.service \
  /etc/systemd/system/hada-supervisor.service
systemctl daemon-reload
systemctl enable docker

echo "Bootstrap complete. Create /opt/hada/.env, configure config/hada.yaml, then run scripts/validate-host.sh."
