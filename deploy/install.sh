#!/usr/bin/env bash
# Install or update the Onecta → Modbus bridge on Debian/Ubuntu (e.g. a Proxmox LXC).
# Run as root from a checkout of this repository:  ./deploy/install.sh
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/onecta-modbus
SERVICE_USER=onecta-modbus

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo $0)" >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv >/dev/null

python3 - <<'EOF'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"Python 3.9+ required, found {sys.version.split()[0]}")
EOF

echo "==> Creating service user"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"

echo "==> Installing the bridge into $PREFIX"
mkdir -p "$PREFIX"
[[ -d "$PREFIX/venv" ]] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q --upgrade "$SRC"

echo "==> Installing systemd service"
[[ -f /etc/onecta-modbus.env ]] || install -m 0644 "$SRC/deploy/onecta-modbus.env" /etc/onecta-modbus.env
install -m 0644 "$SRC/deploy/onecta-modbus.service" /etc/systemd/system/onecta-modbus.service
systemctl daemon-reload
systemctl enable onecta-modbus >/dev/null
systemctl restart onecta-modbus

sleep 2
systemctl --no-pager --lines=5 status onecta-modbus || true
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PORT="$(grep -E '^ONECTA_WEB_PORT=' /etc/onecta-modbus.env | cut -d= -f2 || true)"
echo
echo "Done. Open http://${IP:-<this-host>}:${PORT:-8080} to log in with Daikin."
