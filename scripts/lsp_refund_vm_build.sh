#!/usr/bin/env bash
# Build an independent Linux bundle; product sources and macOS outputs are untouched.
set -euo pipefail
test "$(uname -s)" = Linux
test "$(uname -m)" = aarch64
cd /workspace
test "$(git -C download/fiber/source-pr-1623 rev-parse HEAD)" = 04c206465b48da85b99aa58e80afe9801a2cb2db
git -C download/fiber/source-pr-1623 diff --exit-code HEAD --
test ! -e download/fiber/pr-1623-04c2064/fnn
test ! -e venv
python3 -m venv venv
venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt -r test_cases/fiber/devnet/lsp/requirements.txt
venv/bin/python -m pip freeze > /tmp/lsp-python-freeze.txt
# Fixed installer; toolchain and project target selection come from the fixed source.
installer=https://static.rust-lang.org/rustup/archive/1.28.2/aarch64-unknown-linux-gnu/rustup-init
curl --fail --location --connect-timeout 20 --max-time 300 -o /tmp/rustup-init "$installer"
curl --fail --location --connect-timeout 20 --max-time 30 -o /tmp/rustup-init.sha256 "$installer.sha256"
rustup_sha=$(awk '{print $1}' /tmp/rustup-init.sha256)
[[ "$rustup_sha" =~ ^[0-9a-f]{64}$ ]]
printf '%s  rustup-init\n' "$rustup_sha" | (cd /tmp && sha256sum -c -)
chmod 700 /tmp/rustup-init
/tmp/rustup-init -y --profile minimal --default-toolchain 1.95.0 --no-modify-path
export PATH="$HOME/.cargo/bin:$PATH"
export CARGO_BUILD_JOBS=2
export CARGO_PROFILE_DEV_DEBUG=0
rustc --version | tee /tmp/lsp-rustc-version.txt
cargo --version | tee /tmp/lsp-cargo-version.txt
grep -E '^rustc 1\.95\.0 ' /tmp/lsp-rustc-version.txt
grep -E '^cargo 1\.95\.0 ' /tmp/lsp-cargo-version.txt
test -f download/fiber/pr-1623-04c2064/driver-build/Cargo.lock
cp download/fiber/pr-1623-04c2064/driver-build/Cargo.lock /tmp/reviewed-driver.lock
# The existing builder is offline for its driver; populate a fresh guest cache
# from the reviewed lock without changing any dependency resolution.
venv/bin/python - <<'PY'
from pathlib import Path
p = Path('download/fiber/pr-1623-04c2064/driver-build/Cargo.toml')
text = p.read_text()
old = '/Users/sunchengzhu/project/fiber-py-integration-test/download/fiber/source-pr-1623/'
new = '/workspace/download/fiber/source-pr-1623/'
assert text.count(old) == 4
p.write_text(text.replace(old, new))
PY
cargo fetch --locked --manifest-path download/fiber/pr-1623-04c2064/driver-build/Cargo.toml
cmp /tmp/reviewed-driver.lock download/fiber/pr-1623-04c2064/driver-build/Cargo.lock
venv/bin/python scripts/build_lsp_test_binaries.py --source download/fiber/source-pr-1623
cmp /tmp/reviewed-driver.lock download/fiber/pr-1623-04c2064/driver-build/Cargo.lock
git -C download/fiber/source-pr-1623 diff --exit-code HEAD --
download/fiber/pr-1623-04c2064/fnn --version
test -z "$(find tmp -mindepth 1 -print -quit)"
cp /tmp/lsp-python-freeze.txt /tmp/lsp-ckb-version.txt /tmp/lsp-cli-version.txt /tmp/lsp-rustc-version.txt /tmp/lsp-cargo-version.txt vm-evidence/
df -B1 /workspace
