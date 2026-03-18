#!/bin/bash

set -ex

if [ $# -lt 1 ]; then
  echo "Usage: bash prepare_pr.sh <pr-number>" >&2
  exit 1
fi

PR_NUMBER="$1"
DEFAULT_FIBER_URL="https://github.com/nervosnetwork/fiber.git"
GitFIBERUrl="${GitUrl:-$DEFAULT_FIBER_URL}"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="${ROOT_DIR}/download/fiber/pr${PR_NUMBER}"
TMP_BASE="${TMPDIR:-/tmp}"
WORKDIR="$(mktemp -d "${TMP_BASE}/fiber-pr-${PR_NUMBER}-XXXXXX")"

cleanup() {
  rm -rf "${WORKDIR}"
}

trap cleanup EXIT

cp "${ROOT_DIR}/download/0.202.0/ckb-cli" "${ROOT_DIR}/source/ckb-cli"
git clone --depth 1 "${GitFIBERUrl}" "${WORKDIR}"
git -C "${WORKDIR}" fetch --depth 1 "${GitFIBERUrl}" "pull/${PR_NUMBER}/head:pr-${PR_NUMBER}"
git -C "${WORKDIR}" checkout "pr-${PR_NUMBER}"

TOOLCHAIN=""
if [ -f "${WORKDIR}/rust-toolchain.toml" ]; then
  TOOLCHAIN="$(sed -n 's/^channel = "\(.*\)"/\1/p' "${WORKDIR}/rust-toolchain.toml" | head -1)"
elif [ -f "${WORKDIR}/rust-toolchain" ]; then
  TOOLCHAIN="$(head -1 "${WORKDIR}/rust-toolchain" | tr -d '[:space:]')"
fi

CARGO_CMD=(cargo)
if [ -n "${TOOLCHAIN}" ]; then
  if ! rustup toolchain list | grep -q "^${TOOLCHAIN}"; then
    rustup toolchain install "${TOOLCHAIN}"
  fi
  CARGO_CMD+=("+${TOOLCHAIN}")
fi

mkdir -p "${OUTPUT_DIR}"

(
  cd "${WORKDIR}"
  "${CARGO_CMD[@]}" build --locked
  cp target/debug/fnn "${OUTPUT_DIR}/fnn.debug"
  cp target/debug/fnn-cli "${OUTPUT_DIR}/fnn-cli.debug"
  "${CARGO_CMD[@]}" build --locked --release
  cp target/release/fnn "${OUTPUT_DIR}/fnn"
  cp target/release/fnn-cli "${OUTPUT_DIR}/fnn-cli"
)
