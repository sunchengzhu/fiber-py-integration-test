"""Daily Fiber graph-sync duration benchmark (mainnet / testnet).

Starts a dedicated fnn node from an empty data directory against the official
config + bootnodes, and measures how long the network graph takes to converge.
See framework/daily_graph_sync.py for the exact convergence predicate.

This is a *standalone* benchmark: it does not use the shared devnet Fiber fixtures
and runs trace-level gossip logging only on its own node, so other test cases are
unaffected. It is wired into the ``daily-graph-sync`` GitHub workflow, not the
regular devnet suite -- and is skipped unless ``DAILY_SYNC_ENABLED`` is set, so a
plain ``pytest`` collection never spawns a public-network node by accident.

Selection / overrides come from environment variables:
    DAILY_SYNC_ENABLED     "1"/"true"/"yes" to actually run (else skipped)
    DAILY_SYNC_NETWORK     "mainnet" | "testnet"   (default: testnet)
    DAILY_SYNC_ATTEMPTS    number of attempts, 1 or 2 (default: 1)
    DAILY_SYNC_FNN         path to the built fnn binary
    DAILY_SYNC_CONFIG      path to the official config.yml
    DAILY_SYNC_CKB_URL     CKB JSON-RPC url override (default: public node)
    DAILY_SYNC_EXPECTED_SHA  expected fnn commit SHA (asserted against node_info)
"""

import json
import logging
import os

import pytest

from framework.daily_graph_sync import (
    PUBLIC_CKB_RPC,
    resolve_config_path,
    resolve_fnn_path,
    run_attempt,
)
from framework.util import get_project_root

LOGGER = logging.getLogger(__name__)

ENABLED = os.environ.get("DAILY_SYNC_ENABLED", "").lower() in ("1", "true", "yes")
NETWORK = os.environ.get("DAILY_SYNC_NETWORK", "testnet")


def _parse_attempts():
    """Parse DAILY_SYNC_ATTEMPTS lazily (inside the test), so a bad value only

    errors when the benchmark is actually enabled -- an invalid value must never
    break plain ``pytest`` collection of the skipped test.
    """
    raw = os.environ.get("DAILY_SYNC_ATTEMPTS", "1")
    try:
        value = int(raw)
    except ValueError:
        raise AssertionError(
            f"DAILY_SYNC_ATTEMPTS must be an integer 1 or 2, got {raw!r}"
        )
    assert 1 <= value <= 2, f"DAILY_SYNC_ATTEMPTS must be 1 or 2, got {value}"
    return value


@pytest.mark.skipif(
    not ENABLED,
    reason="daily graph-sync benchmark is opt-in; set DAILY_SYNC_ENABLED=1 to run",
)
def test_daily_graph_sync():
    assert NETWORK in ("mainnet", "testnet"), f"unknown network {NETWORK}"
    attempts = _parse_attempts()

    fnn_path = resolve_fnn_path(os.environ.get("DAILY_SYNC_FNN"))
    config_path = resolve_config_path(NETWORK, os.environ.get("DAILY_SYNC_CONFIG"))
    ckb_url = os.environ.get("DAILY_SYNC_CKB_URL") or PUBLIC_CKB_RPC[NETWORK]
    expected_sha = os.environ.get("DAILY_SYNC_EXPECTED_SHA") or None
    report_root = os.path.join(
        get_project_root(), "report", "daily-graph-sync", NETWORK
    )

    results = []
    for attempt in range(1, attempts + 1):
        report_dir = os.path.join(report_root, f"attempt-{attempt}")
        LOGGER.info("=== daily graph sync: %s attempt %d ===", NETWORK, attempt)
        result = run_attempt(
            NETWORK,
            fnn_path,
            config_path,
            report_dir,
            ckb_url,
            expected_commit_hash=expected_sha,
        )
        results.append(result)
        print(
            f"\n[{NETWORK} attempt {attempt}] "
            + json.dumps(
                {
                    "converged": result.converged,
                    "sync_duration_seconds": result.converged_observed_seconds,
                    "converged_observed_seconds": result.converged_observed_seconds,
                    "active_sync_finished_observed_seconds": result.active_sync_finished_observed_seconds,
                    "graph_cardinality_last_change_seconds": result.graph_cardinality_last_change_seconds,
                    "last_digest_change_seconds": result.last_digest_change_seconds,
                    "node_count": result.node_count,
                    "channel_count": result.channel_count,
                    "peers_final": result.peers_final,
                    "peer_set_changes": result.peer_set_changes,
                    "fiber_version": result.fiber_version,
                    "fiber_commit_hash": result.fiber_commit_hash,
                    "commit_hash_verified": result.commit_hash_verified,
                    "chain_hash": result.chain_hash,
                    "bootnode_seen": result.bootnode_seen,
                    "node_log_bytes": result.node_log_bytes,
                    "node_log_capped": result.node_log_capped,
                    "artifact_failure": result.artifact_failure,
                    "retryable": result.retryable,
                    "cleanup_failure": result.cleanup_failure,
                    "failure_reason": result.failure_reason,
                },
                indent=2,
            ),
            flush=True,
        )
        # A cleanup failure means a node may still be talking to the public
        # network (or a work dir was left behind): abort immediately, never let a
        # later success paper over it.
        if result.cleanup_failure or result.artifact_failure:
            break
        # Stop as soon as one attempt converges; a second attempt only exists to
        # absorb a *transient* public-network hiccup, so don't retry a config /
        # chain / binary error that a retry would only repeat.
        if result.converged:
            break
        if result.retryable is False:
            break

    # No attempt may leave a cleanup failure behind (leaked process / work dir).
    cleanup_failed = [r for r in results if r.cleanup_failure]
    assert not cleanup_failed, (
        f"{NETWORK}: cleanup failed on {len(cleanup_failed)} attempt(s); "
        f"first: {cleanup_failed[0].cleanup_failure}"
    )
    artifact_failed = [r for r in results if r.artifact_failure]
    assert not artifact_failed, (
        f"{NETWORK}: artifact creation failed on {len(artifact_failed)} attempt(s); "
        f"first: {artifact_failed[0].artifact_failure}"
    )

    converged = [r for r in results if r.converged]
    assert converged, (
        f"{NETWORK}: graph did not converge in any of {len(results)} attempt(s); "
        f"last reason: {results[-1].failure_reason}"
    )
    best = converged[-1]
    assert best.node_count > 0 and best.channel_count > 0, (
        f"{NETWORK}: converged but graph empty "
        f"(nodes={best.node_count}, channels={best.channel_count})"
    )
    if expected_sha:
        assert best.commit_hash_verified, (
            f"{NETWORK}: DAILY_SYNC_EXPECTED_SHA={expected_sha} was set but the "
            f"benchmarked fnn commit was not verified "
            f"(commit_hash={best.fiber_commit_hash!r})"
        )
