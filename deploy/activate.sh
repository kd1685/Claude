#!/usr/bin/env bash
# Activate the whole Kingdom 1685 tracker on a fresh Ubuntu/Debian VPS.
# Installs Docker, sets up the firewall, then runs the interactive setup
# (preflight + .env + bring the stack up).
#
#   git clone <your-repo-url> rok1685 && cd rok1685
#   sudo bash deploy/activate.sh
#
set -euo pipefail

# Need root for apt / docker install / firewall — re-exec with sudo if not.
if [ "$(id -u)" -ne 0 ]; then
  echo "Re-running with sudo…"
  exec sudo -E bash "$0" "$@"
fi

cd "$(dirname "$0")/.."          # repo root
REAL_USER="${SUDO_USER:-root}"

echo "================================================="
echo " Kingdom 1685 — full VPS activation"
echo "================================================="

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This bootstrap targets Ubuntu/Debian. On another distro, install Docker"
  echo "+ the compose plugin yourself, then run:  bash deploy/setup.sh"
  exit 1
fi

# ---- 1. base packages ----
echo; echo "[1/4] Installing base packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq ca-certificates curl git openssl ufw

# ---- 2. Docker ----
echo; echo "[2/4] Installing Docker…"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "  Docker + compose already present — skipping."
else
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true
# Let the normal user run docker without sudo later.
if [ "$REAL_USER" != "root" ]; then usermod -aG docker "$REAL_USER" 2>/dev/null || true; fi

# ---- 3. Firewall ----
echo; echo "[3/4] Firewall"
read -r -p "  Configure UFW to allow only SSH, HTTP(80) and HTTPS(443)? [Y/n] " fw
case "${fw:-Y}" in
  [Nn]*) echo "  Skipping firewall (configure it yourself — keep ADB 5555 private!)";;
  *)
    ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1 || true
    ufw allow 80/tcp  >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    yes | ufw enable  >/dev/null 2>&1 || true
    echo "  UFW enabled: SSH + 80 + 443 open; everything else (incl. ADB 5555) closed."
    ;;
esac

# ---- 4. Hand off to the interactive setup ----
echo; echo "[4/4] Running setup (preflight + settings + start)…"
echo
exec bash deploy/setup.sh
