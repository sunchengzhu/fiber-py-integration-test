#!/usr/bin/env bash
# Explicit natural-time refund run; no VM and no clock changes.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
run=${1:-"$repo/report/lsp-refund-natural-$(date +%Y%m%dT%H%M%S)"}
mkdir -p "$run"
export LSP_TEST_BUNDLE="${LSP_TEST_BUNDLE:-$repo/download/fiber/pr-1623-56c761c-refund-natural5}"
export LSP_TEST_REVISION=56c761c45c271c086b05c8d5ea3e033448f5fdf8
export LSP_RETEST_REVISION=56c761c45c271c086b05c8d5ea3e033448f5fdf8
export LSP_RUN_ARTIFACTS="$run/artifacts"
export LSP_PAYMENT_REPORT_DIR="$run"
exec "$repo/venv/bin/python" -m pytest -o addopts= -vv -s --tb=short \
  --run-lsp-refund-nightly \
  "$repo/test_cases/fiber/devnet/lsp_nightly/test_tlc_timeout_refund.py::TestTlcTimeoutRefund::test_hold_payment_timeout_refund"
