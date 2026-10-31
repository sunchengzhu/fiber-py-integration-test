#!/usr/bin/env bash
# One explicitly requested overnight batch, never a daily scheduler.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if test "$#" -eq 0 || { test "$#" -eq 1 && { test "$1" = --check || test "$1" = --help; }; }; then
  exec "$repo/venv/bin/python" "$repo/scripts/lsp_refund_vm_launch.py" "$@"
fi
test "$(uname -s)" = Darwin
test "$#" -eq 4 -o "$#" -eq 5
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
run_dir=$1
payload=$2
payload_sha=$3
system_started_mono=$4
build_budget_args=()
if test "$#" -eq 5; then
  build_budget_args=(--build-started-mono "$5")
fi
case "$run_dir" in "$repo"/report/*) ;; *) exit 2 ;; esac
test -d "$run_dir"
test -f "$payload"
# A launch lock is consumed even when preparation fails; no automatic reruns.
(set -C; : > "$run_dir/nightly-launch.lock")
printf '%s\n' "$$" > "$run_dir/nightly.pid"
trap 'result=$?; printf "%s\n" "$result" > "$run_dir/nightly.exit"' EXIT
cd "$repo"
python_bin="$repo/venv/bin/python"
lima_bin="$repo/download/lsp-refund-vm/tools/lima-2.2.1/bin/limactl"
printf '%s\n' preparing > "$run_dir/nightly.stage"
"$python_bin" scripts/lsp_refund_vm.py --limactl "$lima_bin" \
  --output "$run_dir/preparation" prepare --payload "$payload" \
  --payload-sha256 "$payload_sha" --system-started-mono "$system_started_mono" \
  --system-script scripts/lsp_refund_vm_system.sh --build-script scripts/lsp_refund_vm_build.sh \
  ${build_budget_args[@]+"${build_budget_args[@]}"}
printf '%s\n' verifying > "$run_dir/nightly.stage"
"$python_bin" scripts/lsp_refund_vm.py --limactl "$lima_bin" \
  --output "$run_dir/batch" run --base-manifest "$run_dir/preparation/base.json"
printf '%s\n' complete > "$run_dir/nightly.stage"
