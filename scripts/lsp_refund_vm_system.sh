#!/usr/bin/env bash
# Reviewed dedicated guest preparation; never run on the macOS host.
set -euo pipefail
test "$(uname -s)" = Linux
test "$(uname -m)" = aarch64
test -d /workspace/download/fiber/source-pr-1623/.git
cd /workspace
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  build-essential clang libclang-dev libssl-dev pkg-config cmake git curl \
  ca-certificates python3 python3-venv iptables xz-utils unzip rsync zlib1g-dev lsof
# Disabling guest synchronization is separate from Lima plain's host-sync setting.
# Ask systemd to disable synchronization before masking its last NTP provider.
# With no provider, systemd rejects set-ntp even when NTP is already disabled.
case "$(timedatectl show -p CanNTP --value)" in
  yes) sudo -n timedatectl set-ntp false ;;
  no) test "$(timedatectl show -p NTP --value)" = no ;;
  *) exit 1 ;;
esac
for service in systemd-timesyncd chrony chronyd ntp ntpd; do
  sudo -n systemctl disable --now "$service" 2>/dev/null || true
  sudo -n systemctl mask "$service" 2>/dev/null || true
done
test "$(timedatectl show -p NTP --value)" = no
for service in systemd-timesyncd chrony chronyd ntp ntpd; do
  load=$(systemctl show "$service" -p LoadState --value)
  case "$load" in
    not-found) printf '%s: not installed\n' "$service" ;;
    loaded|masked) test "$(systemctl show "$service" -p ActiveState --value)" = inactive ;;
    *) exit 1 ;;
  esac
done
timedatectl show
printf '%s  %s\n' \
  2324a81c3c5eef3cba43de6e80efde7f86e3ec2dcb1cfab114074cf99784cbec \
  download/lsp-refund-vm/assets/ckb_v0.202.0_aarch64-unknown-linux-gnu.tar.gz | sha256sum -c -
mkdir -p download/0.202.0
tar -xzf download/lsp-refund-vm/assets/ckb_v0.202.0_aarch64-unknown-linux-gnu.tar.gz \
  --strip-components=1 -C download/0.202.0
test ! -e source/ckb-cli
ln -s ../download/0.202.0/ckb-cli source/ckb-cli
download/0.202.0/ckb --version | tee /tmp/lsp-ckb-version.txt
download/0.202.0/ckb-cli --version | tee /tmp/lsp-cli-version.txt
grep -E '^ckb 0\.202\.0 ' /tmp/lsp-ckb-version.txt
grep -E '^ckb-cli 1\.15\.0 ' /tmp/lsp-cli-version.txt
mkdir -p tmp vm-evidence
test -z "$(find tmp -mindepth 1 -print -quit)"
df -B1 /workspace
