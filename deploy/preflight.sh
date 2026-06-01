#!/usr/bin/env bash
# Preflight: will the Rise of Kingdoms bot (Android emulator over ADB) run on
# THIS machine? The website + API + database run on any VPS; the only part with
# special requirements is the Android instance the bot drives.
#
# Run on the VPS:  bash deploy/preflight.sh
set -u

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }

echo "== Website + API + DB (works on essentially any Linux VPS) =="
command -v docker >/dev/null 2>&1 && ok "docker installed" || bad "docker not installed — curl -fsSL https://get.docker.com | sh"
docker compose version >/dev/null 2>&1 && ok "docker compose plugin present" || warn "docker compose plugin missing"

echo
echo "== Android emulator for the bot (redroid) — needs host kernel binder support =="
fail=0
if [ -e /dev/binderfs ] || [ -d /sys/kernel/binderfs ]; then
  ok "binderfs available"
elif lsmod 2>/dev/null | grep -q binder; then
  ok "binder module loaded"
else
  if modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null; then
    ok "binder_linux module loadable (loaded it now)"
  else
    bad "no binder support — redroid will NOT start on this kernel"
    fail=1
  fi
fi

if [ -e /dev/kvm ]; then ok "/dev/kvm present (KVM available — also enables full Android emulators)";
else warn "/dev/kvm absent (fine for redroid; needed only for the Google Android emulator)"; fi

echo
if [ "$fail" = "0" ]; then
  echo "Result: this host can run the redroid Android emulator → the bot can run here."
else
  cat <<EOF
Result: this host CANNOT run redroid (kernel lacks binder).
Your options for the bot:
  1. Use a VPS/host where you control the kernel (bare-metal, or a provider whose
     kernel has CONFIG_ANDROID_BINDERFS — many KVM VPSes do; OpenVZ/LXC usually don't).
  2. Run a full Android emulator on a KVM host (needs /dev/kvm).
  3. Point ADB at a remote/physical Android device:
       set CONTROL_BACKEND=adb and ADB_CONNECT=<phone-ip>:5555
The website, API, scans display and accounts all work regardless — only the live
control/scan actions need a reachable Android instance.
EOF
fi
