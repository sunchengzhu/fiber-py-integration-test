"""Daily Fiber graph-sync benchmark engine (isolated from the shared framework).

This module starts a *dedicated* fnn process against the official mainnet/testnet
config, lets it connect to the official bootnodes from an empty data directory, and
measures how long the network graph takes to converge (caliber A2 in the proposal):

    历史上曾 finished > 0                          (ever_finished)
    AND 当前 active == 0                           (no peer still actively syncing)
    AND finished + passive == total_peers          (all connected peers done)
    AND aggregate 描述的是*当前* peer 集合          (see the peer-generation gate below)
    AND remote graph 非空
    AND 节点/通道内容在 completion 信号后仍稳定 STABLE_WINDOW 秒

Peer-generation gate: ``list_peers`` alone cannot prove that a same-pubkey
reconnect is the *same* gossip session, so we do NOT claim session identity.
Instead we fingerprint the current peer set (pubkey + address), reset the stable
window whenever that fingerprint changes, and require a *fresh* aggregate trace
line emitted AFTER the last change (a strictly greater ``AggregateReader.seq``).
That way a stale aggregate describing an old — but equal-count — peer set can
never satisfy completion, so an A→C peer swap can't produce a false "converged".

It intentionally does NOT reuse ``framework.test_fiber.Fiber`` (whose shared
``start()`` uses ``RUST_LOG=info,fnn={level}`` and cannot express the
``fnn::fiber::gossip=trace`` target we need). Running trace only on this dedicated
node keeps every other devnet test case unaffected.

The work dir is a private ``tempfile.mkdtemp()`` OUTSIDE the report tree, the
plaintext secret keys are unlinked immediately after stop(), and summary.json is
written LAST so it always reflects the final cleanup outcome. Every started
attempt — including one that fails URL validation, CKB precheck or prepare —
produces a redacted summary artifact, and no failure path can leak the secret
key, the data dir or the raw CKB endpoint.

The measured sync phase shares one hard deadline, and every sync-phase RPC is
bounded by its remaining budget. Precheck/setup/stop are reported separately.
"""

import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field, asdict

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants (proposal v5 §3)
# ---------------------------------------------------------------------------
POLL_INTERVAL = 5  # seconds between monitoring iterations
STABLE_WINDOW = 30  # counts must be unchanged this long (after finish signal)
MAX_WAIT = 15 * 60  # single hard deadline per attempt
PER_CALL_TIMEOUT = 20  # per-RPC timeout cap; actual = min(cap, remaining)
RPC_READY_TIMEOUT = 120  # sub-budget (within MAX_WAIT) to see the RPC come up
MAX_SAMPLE_GAP = POLL_INTERVAL * 2  # unobserved time never counts as "stable"
PROGRESS_LOG_INTERVAL = 30  # low-noise CI heartbeat while the long sync is running
PAGE_SIZE = 500  # graph pagination page size
MAX_PAGES = 10000  # pagination safety cap
CKB_TIP_STALE_SECONDS = 3600  # tip header must be newer than this
MAX_NODE_LOG_BYTES = 256 * 1024 * 1024  # fail closed if trace log runs away (256 MiB)

RUST_LOG = "info,fnn::fiber::gossip=trace"

GENESIS = {
    "mainnet": "0x92b197aa1fba0f63633922c61c92375c9c074a93e85963554f5499fe1450d0e5",
    "testnet": "0x10639e0895502b5688a6be8cf69460d76541bfa4821629d86d62ba0aae3f9606",
}

PUBLIC_CKB_RPC = {
    "mainnet": "https://mainnet.ckbapp.dev/",
    "testnet": "https://testnet.ckbapp.dev/",
}

# gossip.rs maintenance trace line (crate target = fnn):
#   "Gossip network maintenance ticked, current state: num of peers: N,
#    num of finished syncing peers: N, num of active syncing peers: N,
#    num of passive syncing peers: N"
_AGG_RE = re.compile(
    r"num of peers:\s*(\d+),\s*"
    r"num of finished syncing peers:\s*(\d+),\s*"
    r"num of active syncing peers:\s*(\d+),\s*"
    r"num of passive syncing peers:\s*(\d+)"
)


class DeadlineExceeded(Exception):
    pass


class NodeExited(Exception):
    pass


class GraphError(Exception):
    """Pagination or graph-shape anomaly; must fail the attempt (fail closed)."""


class ConfigError(Exception):
    """The official config or running binary does not match the expected target."""


class NodeLogError(Exception):
    """node.log grew past the cap or was truncated/rotated under us."""


class CleanupError(Exception):
    """The dedicated fnn process or its private work dir could not be cleaned."""


@dataclass
class SyncAggregate:
    total: int
    finished: int
    active: int
    passive: int

    @property
    def all_connected_finished(self) -> bool:
        # A2 (current-complete half): no peer is still actively syncing, and every
        # connected peer has either finished its active sync or moved on to passive
        # syncing. NOTE: this must NOT require finished > 0 -- once fnn's maintenance
        # tick flips finished peers to PassiveFilter, the legitimate completed state
        # is total=N, finished=0, active=0, passive=N. The historical "finished was
        # once > 0" signal is tracked separately (ever_finished) so it is never lost.
        return (
            self.total > 0
            and self.active == 0
            and self.finished + self.passive == self.total
        )


@dataclass
class SyncResult:
    network: str
    converged: bool = False
    failure_reason: str = ""
    # primary metric (proposal v5 §1)
    converged_observed_seconds: float = None
    # protocol metric: first time aggregate finished>0 was observed
    active_sync_finished_observed_seconds: float = None
    # diagnostics
    graph_cardinality_last_change_seconds: float = None
    last_digest_change_seconds: float = None
    node_count: int = 0
    channel_count: int = 0
    nodes_digest: str = ""
    channels_digest: str = ""
    bootnode_seen: bool = False
    bootnodes_configured: list = field(default_factory=list)
    bootnodes_matched: list = field(default_factory=list)
    final_sync_aggregate: dict = None
    fiber_version: str = ""
    fiber_commit_hash: str = ""
    expected_commit_hash: str = ""
    commit_hash_verified: bool = False
    chain_hash: str = ""
    rpc_ready_seconds: float = None
    ckb_precheck_seconds: float = None
    prepare_seconds: float = None
    sync_seconds: float = None
    stop_seconds: float = None
    trace_instrumentation_enabled: bool = True
    node_log_bytes: int = 0
    node_log_capped: bool = False
    artifact_failure: str = ""
    cleanup_failure: str = ""
    retryable: bool = None
    peers_final: int = 0
    peer_set_changes: int = 0
    final_aggregate_seq: int = 0
    env_override_keys: list = field(default_factory=list)
    env_stripped_keys: list = field(default_factory=list)
    ckb_precheck: dict = None
    samples: list = field(default_factory=list)

    def to_dict(self):
        data = asdict(self)
        # Human-facing alias for the primary metric. Keep the original field for
        # compatibility with the proposal and existing report consumers.
        data["sync_duration_seconds"] = self.converged_observed_seconds
        return data


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _redact(url: str) -> str:
    """Return only scheme://host[:port] so tokens/paths never hit logs/artifacts."""
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        host = p.hostname or ""
        port = f":{p.port}" if p.port else ""
        return f"{p.scheme}://{host}{port}"
    except Exception:
        return "<redacted>"


def _progress(network, message, sync_start=None, **fields):
    """Print one flush-safe, single-line progress event for GitHub Actions.

    The detailed fnn trace remains in ``node.log.gz``; these intentionally sparse
    milestones make the live CI log useful without flooding it. Callers must only
    pass already-redacted/public values.
    """
    if sync_start is None:
        prefix = f"[daily-graph-sync:{network}]"
    else:
        elapsed = max(0.0, time.monotonic() - sync_start)
        prefix = f"[daily-graph-sync:{network} +{elapsed:.1f}s]"

    details = []
    for key, value in fields.items():
        if value is None:
            continue
        single_line = re.sub(r"\s+", " ", str(value)).strip()
        details.append(f"{key}={single_line}")
    suffix = f" {' '.join(details)}" if details else ""
    print(f"{prefix} {message}{suffix}", flush=True)


def validate_public_ckb_url(url: str):
    """Fail closed unless ``url`` is a plain, path-less public endpoint.

    A CKB URL is only ever a bare JSON-RPC endpoint for this benchmark, so we
    refuse anything that could smuggle a secret into requests exception text, the
    archived node.log or summary.json. We reject (fail closed) unless ALL hold:

      * scheme is https (http is tolerated only for a loopback host, for local
        dev against a self-hosted node -- never for a remote plaintext endpoint);
      * a hostname is present;
      * there is no userinfo (``user:pass@``);
      * there is no query string or fragment;
      * the path is empty or exactly ``/`` (a ``/secret-token`` path is refused).
    """
    from urllib.parse import urlparse

    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    if not host:
        raise ConfigError("CKB URL must contain a hostname")
    is_loopback = host in ("127.0.0.1", "localhost", "::1")
    if not (p.scheme == "https" or (p.scheme == "http" and is_loopback)):
        raise ConfigError(
            "CKB URL must be https (plain http is allowed only for a loopback host)"
        )
    if p.username or p.password or "@" in (p.netloc or ""):
        raise ConfigError(
            "CKB URL must not contain credentials (userinfo); "
            "use a plain public endpoint"
        )
    if p.query or p.fragment:
        raise ConfigError(
            "CKB URL must not contain a query string or fragment "
            "(possible token); use a plain public endpoint"
        )
    if p.path not in ("", "/"):
        raise ConfigError(
            "CKB URL must not contain a path (possible token); "
            "use a plain public endpoint"
        )


def _safe_reason(exc, *secrets) -> str:
    """Build a ``Type: message`` string with any secret substrings redacted.

    requests exceptions embed the full request URL, so even a validated endpoint
    is passed through ``_redact`` before it can reach failure_reason/summary.json.
    """
    msg = f"{type(exc).__name__}: {exc}"
    for s in secrets:
        if s:
            msg = msg.replace(s, _redact(s))
    return msg


def _to_int(value) -> int:
    """Coerce a JSON number or 0x-hex string to int (0 on anything unparseable)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            return 0
    return 0


def _is_uint(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = int(value, 16) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return False
    return parsed >= 0


def _require_graph_fields(item, fields, context):
    for field_name, predicate in fields.items():
        if field_name not in item or not predicate(item[field_name]):
            raise GraphError(
                f"{context}: missing or invalid required field {field_name!r}"
            )


def _validate_node_item(item):
    """Validate the required GraphNodesResult NodeInfo schema fail-closed."""
    _require_graph_fields(
        item,
        {
            "pubkey": lambda v: isinstance(v, str) and bool(v),
            "timestamp": _is_uint,
            "node_name": lambda v: isinstance(v, str),
            "version": lambda v: isinstance(v, str),
            "addresses": lambda v: isinstance(v, list)
            and all(isinstance(x, str) for x in v),
            "features": lambda v: isinstance(v, list)
            and all(isinstance(x, str) for x in v),
            "chain_hash": lambda v: isinstance(v, str) and bool(v),
            "auto_accept_min_ckb_funding_amount": _is_uint,
            "udt_cfg_infos": lambda v: isinstance(v, list),
        },
        "graph_nodes item",
    )


def _validate_channel_update(update, context):
    if update is None:
        return
    if not isinstance(update, dict):
        raise GraphError(f"{context}: channel update must be an object or null")
    _require_graph_fields(
        update,
        {
            "timestamp": _is_uint,
            "enabled": lambda v: isinstance(v, bool),
            "outbound_liquidity": lambda v: v is None or _is_uint(v),
            "tlc_expiry_delta": _is_uint,
            "tlc_minimum_value": _is_uint,
            "fee_rate": _is_uint,
        },
        context,
    )


def _validate_channel_item(item):
    """Validate the required GraphChannelsResult ChannelInfo schema fail-closed."""
    _require_graph_fields(
        item,
        {
            "channel_outpoint": lambda v: isinstance(v, str) and bool(v),
            "node1": lambda v: isinstance(v, str) and bool(v),
            "node2": lambda v: isinstance(v, str) and bool(v),
            "created_timestamp": _is_uint,
            "capacity": _is_uint,
            "chain_hash": lambda v: isinstance(v, str) and bool(v),
            "udt_type_script": lambda v: v is None or isinstance(v, dict),
        },
        "graph_channels item",
    )
    for side in ("update_info_of_node1", "update_info_of_node2"):
        if side not in item:
            raise GraphError(f"graph_channels item: missing required field {side!r}")
        _validate_channel_update(item[side], f"graph_channels item {side}")


def _peer_fingerprint(peers):
    """Stable identity/address fingerprint for one validated list_peers result."""
    return tuple(sorted((peer["pubkey"], peer["address"]) for peer in peers))


def _sample_gap_exceeded(previous_ts, current_ts):
    """Whether an observation hole is too large to count toward stability."""
    return previous_ts is not None and current_ts - previous_ts > MAX_SAMPLE_GAP


def _jsonrpc(url, method, params, timeout):
    """Single JSON-RPC call, no internal retry (try_count=1, proposal v5 §3.2)."""
    response = requests.post(
        url,
        data=json.dumps(
            {"id": 1, "jsonrpc": "2.0", "method": method, "params": params}
        ),
        headers={"content-type": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as e:
        raise RuntimeError(f"{method}: response is not valid JSON") from e
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{method}: JSON-RPC response must be an object, "
            f"got {type(payload).__name__}"
        )
    if payload.get("jsonrpc") != "2.0":
        raise RuntimeError(f"{method}: response is not a JSON-RPC 2.0 envelope")
    if payload.get("id") != 1:
        raise RuntimeError(
            f"{method}: response id {payload.get('id')!r} does not match request id 1"
        )
    if payload.get("error") is not None:
        raise RuntimeError(f"rpc error {method}: {payload['error']}")
    if "result" not in payload:
        raise RuntimeError(f"{method}: JSON-RPC response is missing result")
    return payload["result"]


def _normalize_multiaddr(addr: str):
    """(host, port, peer_id) for tolerant bootnode matching (proposal v5 §9)."""
    host = port = peer_id = None
    parts = addr.strip().split("/")
    for i, tok in enumerate(parts):
        if tok in ("ip4", "ip6", "dns", "dns4", "dns6") and i + 1 < len(parts):
            host = parts[i + 1]
        elif tok == "tcp" and i + 1 < len(parts):
            port = parts[i + 1]
        elif tok == "p2p" and i + 1 < len(parts):
            peer_id = parts[i + 1]
    return host, port, peer_id


def parse_bootnodes(config_path):
    """Return the official config's ``fiber.bootnode_addrs`` as a list of str."""
    fiber = _fiber_section(config_path)
    return _coerce_addr_list(fiber.get("bootnode_addrs"), "bootnode_addrs")


def parse_announced_addrs(config_path):
    """Return the *active* ``fiber.announced_addrs`` entries (empty if unset).

    The official config ships this key commented out / null, so the list must be
    empty. A non-empty result means the daily node would advertise a (random,
    ephemeral) identity to the public network -- ``prepare()`` refuses to start.
    Parsed with ``yaml.safe_load`` so inline/flow lists, aliases and null are all
    handled the same as fnn's own loader (a regex scan silently missed those).
    """
    fiber = _fiber_section(config_path)
    return _coerce_addr_list(fiber.get("announced_addrs"), "announced_addrs")


def _fiber_section(config_path):
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"config {config_path} is invalid YAML: {e}") from e
    if not isinstance(cfg, dict):
        raise ConfigError(f"config {config_path} is not a YAML mapping")
    fiber = cfg.get("fiber")
    if fiber is None:
        return {}
    if not isinstance(fiber, dict):
        raise ConfigError(f"config {config_path}: 'fiber' section is not a mapping")
    return fiber


def _coerce_addr_list(value, field_name):
    """Normalize a YAML value that should be a list of multiaddr strings."""
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ConfigError(
                    f"config {field_name} has a non-string entry: {item!r}"
                )
            s = item.strip()
            if s:
                out.append(s)
        return out
    raise ConfigError(f"config {field_name} has unexpected type {type(value).__name__}")


# ---------------------------------------------------------------------------
# CKB precheck (proposal v5 §6) — hard assertions before starting fnn
# ---------------------------------------------------------------------------
def ckb_precheck(ckb_url, network):
    if network not in GENESIS:
        raise ConfigError(f"unsupported network {network!r}")
    expected_genesis = GENESIS[network]
    info = {"endpoint": _redact(ckb_url), "network": network}

    genesis = _jsonrpc(ckb_url, "get_block_hash", ["0x0"], timeout=15)
    if not isinstance(genesis, str):
        raise RuntimeError(
            "get_block_hash returned a malformed result " f"({type(genesis).__name__})"
        )
    info["genesis_hash"] = genesis
    if genesis.lower() != expected_genesis.lower():
        raise ConfigError(
            f"CKB genesis mismatch for {network}: got {genesis}, expected {expected_genesis}"
        )

    tip = _jsonrpc(ckb_url, "get_tip_header", [], timeout=15)
    try:
        if not isinstance(tip, dict):
            raise TypeError(f"expected object, got {type(tip).__name__}")
        tip_ts_ms = int(tip["timestamp"], 16)
        tip_number = int(tip["number"], 16)
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"get_tip_header returned a malformed result: {e}") from e
    age = time.time() - tip_ts_ms / 1000.0
    info["tip_number"] = tip_number
    info["tip_age_seconds"] = round(age, 1)
    if age > CKB_TIP_STALE_SECONDS:
        raise RuntimeError(
            f"CKB tip is stale for {network}: age={age:.0f}s > {CKB_TIP_STALE_SECONDS}s"
        )

    latencies = []
    for _ in range(3):
        t0 = time.monotonic()
        _jsonrpc(ckb_url, "get_tip_block_number", [], timeout=15)
        latencies.append(round((time.monotonic() - t0) * 1000, 1))
    info["latency_ms_samples"] = latencies
    info["latency_ms_avg"] = round(sum(latencies) / len(latencies), 1)
    return info


# ---------------------------------------------------------------------------
# Digest (proposal v5 §9) — canonical content hash over the graph.
# The digest answers "did any *content* I care about change?", so it must cover
# the mutable announcement/update fields, not just identities. Ordering must not
# matter (sort arrays + object keys), and it must use the same self-excluded node
# set as the reported node_count. The SAME merge functions dedup both the paging
# stream and the digest, so a duplicate that spans pages can never change either.
# ---------------------------------------------------------------------------
def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _canonical_value(value):
    """Normalize nested JSON values whose list ordering is not graph identity."""
    if isinstance(value, dict):
        return {k: _canonical_value(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        normalized = [_canonical_value(v) for v in value]
        return sorted(normalized, key=_canon)
    return value


def _node_payload(n, self_pk):
    pk = (n.get("pubkey") or "").lower()
    return {
        "pubkey": pk,
        "timestamp": _to_int(n.get("timestamp")),
        "node_name": n.get("node_name") or n.get("name") or "",
        "version": n.get("version") or "",
        "addresses": sorted(n.get("addresses") or []),
        "features": sorted(n.get("features") or []),
        "chain_hash": (n.get("chain_hash") or "").lower(),
        "auto_accept_min_ckb_funding_amount": _to_int(
            n.get("auto_accept_min_ckb_funding_amount")
        ),
        "udt_cfg_infos": _canonical_value(n.get("udt_cfg_infos") or []),
    }


def _merge_node(existing, incoming):
    """Deterministic winner between two node announcements for the same pubkey.

    Higher ``timestamp`` wins; ties break on the canonical payload string so the
    result is independent of the order the two records arrived in (across pages or
    within a page).
    """
    if existing is None:
        return incoming
    te = _to_int(existing.get("timestamp"))
    ti = _to_int(incoming.get("timestamp"))
    if ti != te:
        return incoming if ti > te else existing
    ce = _canon(_node_payload(existing, ""))
    ci = _canon(_node_payload(incoming, ""))
    return incoming if ci > ce else existing


def _pick_newer_update(a, b):
    """Newest single ChannelUpdate for one direction (deterministic on ties)."""
    if a is None:
        return b
    if b is None:
        return a
    ta = _to_int(a.get("timestamp"))
    tb = _to_int(b.get("timestamp"))
    if ta != tb:
        return b if tb > ta else a
    return b if _canon(b) > _canon(a) else a


def _merge_channel(existing, incoming):
    """Merge two records for the same channel_outpoint direction-by-direction.

    A whole-record "keep the one with the max timestamp" merge loses the other
    direction's newer update (e.g. node1 updates in page 1, node2 in page 2), so
    each direction is merged independently and identity fields are folded
    deterministically.
    """
    if existing is None:
        return dict(incoming)
    merged = dict(existing)

    def merge_string_identity(field):
        old = existing.get(field)
        new = incoming.get(field)
        if old and new and str(old).lower() != str(new).lower():
            raise GraphError(
                f"duplicate channel {existing.get('channel_outpoint')!r} has "
                f"conflicting {field}: {old!r} != {new!r}"
            )
        return old or new

    for field_name in ("channel_outpoint", "node1", "node2", "chain_hash"):
        merged[field_name] = merge_string_identity(field_name)

    for field_name in ("created_timestamp", "capacity"):
        old = existing.get(field_name)
        new = incoming.get(field_name)
        if old is not None and new is not None and _to_int(old) != _to_int(new):
            raise GraphError(
                f"duplicate channel {existing.get('channel_outpoint')!r} has "
                f"conflicting {field_name}: {old!r} != {new!r}"
            )
        merged[field_name] = old if old is not None else new

    old_udt = existing.get("udt_type_script")
    new_udt = incoming.get("udt_type_script")
    if (
        old_udt is not None
        and new_udt is not None
        and _canonical_value(old_udt) != _canonical_value(new_udt)
    ):
        raise GraphError(
            f"duplicate channel {existing.get('channel_outpoint')!r} has "
            "conflicting udt_type_script"
        )
    merged["udt_type_script"] = old_udt if old_udt is not None else new_udt

    for side in ("update_info_of_node1", "update_info_of_node2"):
        merged[side] = _pick_newer_update(existing.get(side), incoming.get(side))
    return merged


def _nodes_digest(nodes, self_pubkey=None):
    self_pk = (self_pubkey or "").lower()
    keyed = {}
    for n in nodes:
        pk = (n.get("pubkey") or "").lower()
        if not pk or pk == self_pk:
            continue
        keyed[pk] = _merge_node(keyed.get(pk), n)
    payload = [_node_payload(n, self_pk) for _, n in sorted(keyed.items())]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _channel_payload(c):
    return {
        "outpoint": (c.get("channel_outpoint") or "").lower(),
        "node1": (c.get("node1") or "").lower(),
        "node2": (c.get("node2") or "").lower(),
        "created_timestamp": _to_int(c.get("created_timestamp")),
        "capacity": _to_int(c.get("capacity")),
        "chain_hash": (c.get("chain_hash") or "").lower(),
        "udt_type_script": _canonical_value(c.get("udt_type_script")),
        # include both directional updates verbatim so a fee/enabled/expiry/tlc
        # or timestamp change on either side flips the digest.
        "update1": c.get("update_info_of_node1"),
        "update2": c.get("update_info_of_node2"),
    }


def _channels_digest(channels):
    keyed = {}
    for c in channels:
        outpoint = (c.get("channel_outpoint") or "").lower()
        if not outpoint:
            continue
        keyed[outpoint] = _merge_channel(keyed.get(outpoint), c)
    payload = [_channel_payload(c) for _, c in sorted(keyed.items())]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Incremental node.log aggregate reader (proposal v5 §3; review #1/#7)
# ---------------------------------------------------------------------------
class AggregateReader:
    """Reads only the *newly appended* bytes of node.log each poll.

    Re-reading a multi-GB trace log every 5 s would perturb the very thing we
    measure, so we track a byte offset and carry a partial trailing line between
    polls. Every complete new line is scanned, so a transient ``finished > 0``
    aggregate is captured in ``ever_finished`` even if the next maintenance tick
    has already flipped every peer to passive by the time Python polls.
    """

    def __init__(self, path, max_bytes=MAX_NODE_LOG_BYTES):
        self.path = path
        self.max_bytes = max_bytes
        self.offset = 0
        self._carry = b""
        self.ever_finished = False
        self.latest = None
        self.seq = 0  # monotonically increasing per parsed aggregate line
        self.capped = False

    def poll(self):
        """Consume new bytes; return the most recent aggregate seen so far."""
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            return self.latest
        if size > self.max_bytes:
            self.capped = True
            raise NodeLogError(
                f"node.log exceeded {self.max_bytes} bytes (size={size}); "
                f"failing closed to preserve diagnostics"
            )
        if size < self.offset:
            raise NodeLogError(
                f"node.log shrank (size={size} < offset={self.offset}); "
                f"truncated or rotated under us"
            )
        if size == self.offset:
            return self.latest
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()
        raw = self._carry + chunk
        parts = raw.split(b"\n")
        self._carry = parts.pop()  # trailing partial line, completed next poll
        for bline in parts:
            m = _AGG_RE.search(bline.decode("utf-8", "replace"))
            if m:
                agg = SyncAggregate(
                    total=int(m.group(1)),
                    finished=int(m.group(2)),
                    active=int(m.group(3)),
                    passive=int(m.group(4)),
                )
                self.latest = agg
                self.seq += 1  # a fresh aggregate describing the peer set *now*
                if agg.finished > 0:
                    self.ever_finished = True
        return self.latest


# ---------------------------------------------------------------------------
# Dedicated fnn node lifecycle
# ---------------------------------------------------------------------------
class DailySyncNode:
    def __init__(self, network, fnn_path, official_config_path, attempt_dir, ckb_url):
        self.network = network
        self.fnn_path = os.path.abspath(fnn_path)
        self.official_config_path = official_config_path
        self.attempt_dir = os.path.abspath(attempt_dir)
        self.ckb_url = ckb_url
        self.config_path = os.path.join(self.attempt_dir, "config.yml")
        self.log_path = os.path.join(self.attempt_dir, "node.log")
        self.key_path = os.path.join(self.attempt_dir, "ckb", "key")
        self.fiber_key_path = os.path.join(self.attempt_dir, "fiber", "sk")
        self.rpc_port = _free_tcp_port()
        self.rpc_url = f"http://127.0.0.1:{self.rpc_port}"
        self.password = hashlib.sha256(os.urandom(32)).hexdigest()
        self.proc = None
        self._log_fh = None
        self.bootnodes = []
        self.env_override_keys = []
        self.env_stripped_keys = []
        self.agg_reader = AggregateReader(self.log_path)

    def prepare(self):
        if os.path.lexists(self.attempt_dir):
            if os.path.islink(self.attempt_dir) or not os.path.isdir(self.attempt_dir):
                raise ConfigError("attempt work path is not a real directory")
            if os.listdir(self.attempt_dir):
                raise ConfigError("attempt work directory must start empty")
        else:
            os.makedirs(self.attempt_dir, mode=0o700)
        os.chmod(self.attempt_dir, 0o700)
        ckb_dir = os.path.join(self.attempt_dir, "ckb")
        os.makedirs(ckb_dir, mode=0o700)
        os.chmod(ckb_dir, 0o700)
        # copy the exact-commit official config verbatim (no YAML rewrite)
        shutil.copyfile(self.official_config_path, self.config_path)
        self.bootnodes = parse_bootnodes(self.config_path)
        if not self.bootnodes:
            raise ConfigError(
                f"official {self.network} config has no bootnode_addrs; "
                f"cannot benchmark bootnode-driven sync"
            )
        announced = parse_announced_addrs(self.config_path)
        if announced:
            raise ConfigError(
                f"official {self.network} config advertises announced_addrs "
                f"{announced!r}; refusing to publish an ephemeral identity"
            )
        # Create the random plaintext key atomically at 0600. Opening first and
        # chmodding later leaves a small umask-dependent exposure window.
        fd = os.open(
            self.key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(fd, "w") as f:
            f.write(os.urandom(32).hex())

    def start(self):
        # Strip any inherited FIBER_*/RPC_*/CKB_* so a stray parent variable (e.g.
        # FIBER_ANNOUNCED_ADDRS) can never override the validated official config
        # or bypass the announced-address safety check; keep everything else
        # (PATH, proxies, locale) and then set exactly the vars we control.
        overrides = {
            "FIBER_SECRET_KEY_PASSWORD": self.password,
            "RUST_LOG": RUST_LOG,
            "FIBER_LISTENING_ADDR": "/ip4/127.0.0.1/tcp/0",
            "RPC_LISTENING_ADDR": f"127.0.0.1:{self.rpc_port}",
            "CKB_NODE_RPC_URL": self.ckb_url,
            "FIBER_ANNOUNCE_LISTENING_ADDR": "false",
        }
        stripped = sorted(
            k
            for k in os.environ
            if re.match(r"^(FIBER_|RPC_|CKB_)", k) and k not in overrides
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if not re.match(r"^(FIBER_|RPC_|CKB_)", k)
        }
        env.update(overrides)
        self.env_override_keys = sorted(overrides)
        self.env_stripped_keys = stripped
        self._log_fh = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [self.fnn_path, "-c", self.config_path, "-d", self.attempt_dir],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=True,
        )

    def wait_rpc_ready(self, deadline):
        node_info = None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise NodeExited(
                    f"fnn exited early rc={self.proc.returncode} (see node.log)"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                node_info = _jsonrpc(
                    self.rpc_url, "node_info", [{}], timeout=min(5, remaining)
                )
                if node_info:
                    return node_info
            except (requests.exceptions.RequestException, RuntimeError, ValueError):
                time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise DeadlineExceeded("RPC did not become ready within budget")

    def rpc(self, method, params, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DeadlineExceeded(f"deadline hit before {method}")
        return _jsonrpc(
            self.rpc_url, method, params, timeout=min(PER_CALL_TIMEOUT, remaining)
        )

    def list_peers(self, deadline):
        """Return a strictly validated list_peers snapshot."""
        result = self.rpc("list_peers", [], deadline)
        if not isinstance(result, dict):
            raise GraphError(
                "list_peers: result must be an object, " f"got {type(result).__name__}"
            )
        if "peers" not in result or not isinstance(result["peers"], list):
            raise GraphError("list_peers: result must contain a peers list")
        peers = result["peers"]
        for peer in peers:
            if not isinstance(peer, dict):
                raise GraphError("list_peers: every peer must be an object")
            for field_name in ("pubkey", "address"):
                if not isinstance(peer.get(field_name), str):
                    raise GraphError(f"list_peers: peer has no string {field_name}")
        return peers

    def paginate(self, method, key, deadline, merge):
        """Return (items, scan_seconds), failing closed on any pagination anomaly.

        Contract (verified against fiber graph.rs): a non-empty page always carries
        a strictly-advancing ``last_cursor``; the end of the stream is signalled by
        an *empty* page. So the ONLY clean stop is an empty batch. A non-empty page
        without a cursor, a repeated cursor, an item without identity, or exhausting
        MAX_PAGES all mean we cannot trust the snapshot -> raise, never silently
        return a partial graph that could be mistaken for "converged".

        ``merge(existing, incoming)`` folds a duplicate identity across pages with
        the SAME deterministic rule the digest uses, so a record split across pages
        can never change the reported graph or its digest.
        """
        t0 = time.monotonic()
        items = {}
        after = None
        seen_cursors = set()
        for _ in range(MAX_PAGES):
            res = self.rpc(
                method, [{"limit": hex(PAGE_SIZE), "after": after}], deadline
            )
            if not isinstance(res, dict):
                raise GraphError(
                    f"{method}: result must be an object, " f"got {type(res).__name__}"
                )
            if key not in res:
                raise GraphError(f"{method}: result is missing {key!r}")
            batch = res[key]
            if not isinstance(batch, list):
                raise GraphError(
                    f"{method}: {key!r} must be a list, " f"got {type(batch).__name__}"
                )
            if "last_cursor" not in res or not isinstance(res["last_cursor"], str):
                raise GraphError(f"{method}: result must contain a string last_cursor")
            cursor = res["last_cursor"]
            if not batch:
                return list(items.values()), round(time.monotonic() - t0, 3)
            identity_field = {
                "graph_nodes": "pubkey",
                "graph_channels": "channel_outpoint",
            }.get(method)
            validator = {
                "graph_nodes": _validate_node_item,
                "graph_channels": _validate_channel_item,
            }.get(method)
            if identity_field is None:
                raise GraphError(f"{method}: unsupported paginated graph method")
            for it in batch:
                if not isinstance(it, dict):
                    raise GraphError(
                        f"{method}: item must be an object, " f"got {type(it).__name__}"
                    )
                identity = it.get(identity_field)
                if not isinstance(identity, str) or not identity:
                    raise GraphError(
                        f"{method}: item without string {identity_field} identity"
                    )
                validator(it)
                ident = identity.lower()
                items[ident] = merge(items.get(ident), it)
            if not cursor or cursor == "0x":
                raise GraphError(
                    f"{method}: non-empty page without a last_cursor (got {cursor!r})"
                )
            if cursor in seen_cursors:
                raise GraphError(f"{method}: cursor loop/duplicate ({cursor!r})")
            seen_cursors.add(cursor)
            after = cursor
        raise GraphError(
            f"{method}: exceeded MAX_PAGES={MAX_PAGES} (cursor did not end)"
        )

    def read_latest_aggregate(self):
        """Incrementally consume node.log; return the most recent aggregate."""
        return self.agg_reader.poll()

    def match_bootnodes(self, peers):
        """Bootnodes present in ``peers`` right now.

        Match on the libp2p ``/p2p/<PeerId>`` first: a bootnode configured as a
        DNS name but reported by list_peers as a resolved IP still matches when the
        PeerId is equal. Fall back to host+port only when a PeerId is unavailable
        on either side. (The ``/p2p`` PeerId is a libp2p identity, NOT the Fiber
        secp256k1 pubkey, so the two are never cross-compared.)
        """
        matched = []
        norm_boot = [_normalize_multiaddr(b) for b in self.bootnodes]
        for peer in peers:
            addr = peer.get("address", "")
            ph, pp, ppid = _normalize_multiaddr(addr)
            for bh, bp, bpid in norm_boot:
                hostport_match = bool(
                    bh and ph and bh == ph and (bp is None or pp is None or bp == pp)
                )
                if bpid and ppid:
                    is_match = bpid == ppid
                else:
                    is_match = hostport_match
                if is_match:
                    matched.append(addr)
                    break
        return matched

    def stop(self):
        """Terminate the whole fnn process group, escalating to SIGKILL.

        fnn is spawned with ``start_new_session=True`` so it leads its own
        process group; killing the group reaps any child it may fork. Raises
        CleanupError if the process is still alive after SIGKILL so the caller
        can preserve the work dir for diagnosis instead of silently leaking a
        node that keeps talking to the public network.
        """
        if self._log_fh is not None:
            try:
                self._log_fh.flush()
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            return
        pgid = None
        try:
            pgid = os.getpgid(self.proc.pid)
        except (ProcessLookupError, OSError):
            pgid = None

        def _signal(sig):
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                else:
                    self.proc.send_signal(sig)
            except (ProcessLookupError, OSError):
                pass

        _signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=20)
            return
        except subprocess.TimeoutExpired:
            pass
        _signal(signal.SIGKILL)
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            raise CleanupError(
                f"fnn pid={self.proc.pid} still alive after SIGKILL; "
                f"work dir preserved at {self.attempt_dir}"
            )

    def shred_secret(self):
        """Unlink every plaintext key path and surface any failure.

        Called unconditionally after stop(), regardless of whether stop()
        confirmed the process exited, so that even if clean() later fails (work
        dir preserved for diagnosis) the secret key is already gone and can never
        reach an uploaded artifact.
        """
        failures = []
        for path in (self.key_path, self.fiber_key_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                continue
            except OSError as e:
                failures.append(f"{path}: {e}")
        if failures:
            raise CleanupError("could not remove secret key(s): " + "; ".join(failures))

    def archive_log(self, report_dir, snapshot_size=None):
        """Write node.log.gz into report_dir (must run BEFORE clean()).

        Archive exactly the size observed after stop(). This prevents a leaked
        writer from making gzip chase a growing file forever. Oversized input
        fails before any artifact is installed, and a temporary file is replaced
        atomically only after the bounded copy succeeds.
        """
        os.makedirs(report_dir, exist_ok=True)
        if not os.path.exists(self.log_path):
            return
        if snapshot_size is None:
            snapshot_size = os.path.getsize(self.log_path)
        if snapshot_size > MAX_NODE_LOG_BYTES:
            self.agg_reader.capped = True
            raise NodeLogError(
                f"node.log exceeded {MAX_NODE_LOG_BYTES} bytes "
                f"(size={snapshot_size}); archive omitted"
            )
        destination = os.path.join(report_dir, "node.log.gz")
        temporary = destination + ".tmp"
        try:
            remaining = snapshot_size
            with open(self.log_path, "rb") as src, gzip.open(temporary, "wb") as dst:
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise NodeLogError(
                            "node.log shrank while creating the bounded archive"
                        )
                    dst.write(chunk)
                    remaining -= len(chunk)
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def write_summary(self, report_dir, result: SyncResult):
        """Write summary.json + samples.jsonl (run LAST, after clean())."""
        _write_result_files(report_dir, result)

    def clean(self):
        """Remove the work dir; on failure preserve it and surface CleanupError."""
        if os.path.isdir(self.attempt_dir):
            try:
                shutil.rmtree(self.attempt_dir)
            except OSError as e:
                raise CleanupError(f"could not remove work dir {self.attempt_dir}: {e}")


# ---------------------------------------------------------------------------
# Orchestration — one attempt (proposal v5 §3 monitoring loop)
# ---------------------------------------------------------------------------
def _write_result_files(report_dir, result: SyncResult):
    """Atomically install the small structured artifacts, summary last."""
    os.makedirs(report_dir, mode=0o700, exist_ok=True)
    samples_path = os.path.join(report_dir, "samples.jsonl")
    samples_tmp = samples_path + ".tmp"
    summary_path = os.path.join(report_dir, "summary.json")
    summary_tmp = summary_path + ".tmp"
    try:
        with open(samples_tmp, "w") as f:
            for sample in result.samples:
                f.write(json.dumps(sample) + "\n")
        os.replace(samples_tmp, samples_path)
        with open(summary_tmp, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        # summary is the completion marker and therefore installed last.
        os.replace(summary_tmp, summary_path)
    finally:
        for temporary in (samples_tmp, summary_tmp):
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _append_failure(current, new):
    return f"{current}; {new}" if current else new


def _record_artifact_failure(result, reason):
    result.artifact_failure = _append_failure(result.artifact_failure, reason)
    result.failure_reason = _append_failure(
        result.failure_reason, f"artifact failure: {reason}"
    )
    result.converged = False
    result.retryable = False


def _record_cleanup_failure(result, reason):
    result.cleanup_failure = _append_failure(result.cleanup_failure, reason)
    result.failure_reason = _append_failure(
        result.failure_reason, f"cleanup failure: {reason}"
    )
    result.converged = False
    result.retryable = False


def _extract_commit_token(node_commit):
    """Leading hex commit token from an fnn ``commit_hash`` (e.g. "bc361aa 2026-..").

    We read the node's token deterministically instead of "cleaning" the expected
    value: the expected SHA is validated to be exactly 40 hex up front, so a
    malformed expected value fails loudly rather than being silently coerced.
    """
    m = re.match(r"\s*([0-9a-fA-F]{7,40})", node_commit or "")
    return m.group(1).lower() if m else ""


def _is_retryable(exc) -> bool:
    """Whether a failed attempt may be retried once.

    Retryable = a transient public-network / RPC hiccup that a second attempt
    could clear. Non-retryable = a config/chain/binary/secret/filesystem problem
    (or a cleanup failure) that a retry would only repeat -- those must fail loud.
    """
    # requests exceptions subclass OSError, so transient RPC/network errors must be
    # classified BEFORE the non-retryable OSError bucket below.
    if isinstance(exc, (DeadlineExceeded, requests.exceptions.RequestException)):
        return True
    if isinstance(
        exc, (ConfigError, GraphError, NodeLogError, CleanupError, NodeExited, OSError)
    ):
        return False
    if isinstance(exc, (RuntimeError, ValueError)):
        return True
    return False


def run_attempt(
    network,
    fnn_path,
    config_path,
    report_dir,
    ckb_url=None,
    expected_commit_hash=None,
) -> SyncResult:
    result = SyncResult(network=network)
    result.expected_commit_hash = expected_commit_hash or ""
    node = None
    work_dir = None
    start = None
    ckb_url = ckb_url or PUBLIC_CKB_RPC.get(network, "")
    try:
        _progress(
            network,
            "attempt started",
            endpoint=_redact(ckb_url),
            expected_commit="set" if expected_commit_hash else "not-set",
        )

        # Prepare only the known small artifact names. A rerun of the same attempt
        # must never upload a stale node.log.gz left by an earlier invocation.
        os.makedirs(report_dir, mode=0o700, exist_ok=True)
        for filename in (
            "summary.json",
            "samples.jsonl",
            "node.log.gz",
            "node.log.gz.tmp",
        ):
            try:
                os.unlink(os.path.join(report_dir, filename))
            except FileNotFoundError:
                pass

        if network not in GENESIS:
            raise ConfigError(f"unsupported network {network!r}")
        result.ckb_precheck = {"endpoint": _redact(ckb_url), "network": network}
        if expected_commit_hash:
            exp = str(expected_commit_hash).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}", exp):
                raise ConfigError(
                    "expected commit must be a 40-hex sha, "
                    f"got {expected_commit_hash!r}"
                )

        # 0) validate the endpoint (fail closed) before anything touches it, then
        #    CKB precheck + local prepare, all BEFORE the sync timer starts so the
        #    reported convergence duration is pure network-graph sync, not setup.
        validate_public_ckb_url(ckb_url)
        pc0 = time.monotonic()
        result.ckb_precheck = ckb_precheck(ckb_url, network)
        result.ckb_precheck_seconds = round(time.monotonic() - pc0, 3)
        _progress(
            network,
            "CKB precheck passed",
            endpoint=_redact(ckb_url),
            tip=result.ckb_precheck.get("tip_number"),
            duration_s=result.ckb_precheck_seconds,
        )

        # Work dir lives OUTSIDE report_dir so neither a private key nor the graph
        # database can be swept into the uploaded report tree.
        work_dir = tempfile.mkdtemp(prefix=f"daily-sync-{network}-")
        node = DailySyncNode(network, fnn_path, config_path, work_dir, ckb_url)
        pp0 = time.monotonic()
        node.prepare()
        result.prepare_seconds = round(time.monotonic() - pp0, 3)
        result.bootnodes_configured = list(node.bootnodes)
        _progress(
            network,
            "fnn config prepared",
            bootnodes=len(node.bootnodes),
            duration_s=result.prepare_seconds,
        )

        # 1) spawn the dedicated trace node (timer running)
        start = time.monotonic()
        deadline = start + MAX_WAIT
        node.start()
        result.env_override_keys = node.env_override_keys
        result.env_stripped_keys = node.env_stripped_keys
        _progress(
            network,
            "fnn started",
            start,
            pid=getattr(node.proc, "pid", None),
        )

        # 2) wait for RPC, bounded by min(RPC_READY sub-budget, hard deadline)
        ready_deadline = min(deadline, start + RPC_READY_TIMEOUT)
        node_info = node.wait_rpc_ready(ready_deadline)
        if not isinstance(node_info, dict):
            raise ConfigError(
                "node_info result must be an object, " f"got {type(node_info).__name__}"
            )
        result.rpc_ready_seconds = round(time.monotonic() - start, 1)
        result.fiber_version = node_info.get("version", "")
        self_pubkey = node_info.get("pubkey")
        if not isinstance(self_pubkey, str) or not self_pubkey:
            raise ConfigError("node_info did not contain a valid pubkey")

        # 2a) identity asserts — refuse to benchmark the wrong chain/binary
        chain_hash = node_info.get("chain_hash", "")
        if not isinstance(chain_hash, str):
            raise ConfigError("node_info chain_hash must be a string")
        result.chain_hash = chain_hash
        if chain_hash.lower() != GENESIS[network].lower():
            raise ConfigError(
                f"node chain_hash {chain_hash!r} != {network} genesis "
                f"{GENESIS[network]!r}"
            )
        commit = node_info.get("commit_hash", "") or node_info.get("commit", "")
        result.fiber_commit_hash = commit
        if not isinstance(commit, str):
            raise ConfigError("node_info commit_hash must be a string")
        if commit and "dirty" in commit.lower():
            raise ConfigError(
                f"fnn built from a -dirty tree ({commit!r}); refuse to benchmark "
                f"an unversioned binary"
            )
        if expected_commit_hash:
            exp = str(expected_commit_hash).strip().lower()
            token = _extract_commit_token(commit)
            if not token:
                raise ConfigError(
                    f"expected commit {exp} but node reported no usable commit "
                    f"token (commit_hash={commit!r}); refuse an unverifiable binary"
                )
            if exp.startswith(token) or token.startswith(exp):
                result.commit_hash_verified = True
            else:
                raise ConfigError(
                    f"fnn commit {commit!r} (token {token}) != expected {exp}"
                )
        _progress(
            network,
            "RPC ready; node identity validated",
            start,
            rpc_ready_s=result.rpc_ready_seconds,
            version=result.fiber_version or "unknown",
            commit=_extract_commit_token(commit) or "unavailable",
            commit_verified=(
                result.commit_hash_verified if expected_commit_hash else "not-required"
            ),
        )

        # 3) monitoring loop
        prev_count = prev_digest = None
        last_count_change_ts = last_digest_change_ts = start
        ever_finished = False
        first_finished_ts = None
        completion_since = None
        latest_agg = None
        bootnode_seen = False
        peers_len = 0
        prev_peer_fp = None
        peer_change_seq = 0
        peer_set_changes = 0
        last_successful_sample_ts = None
        next_poll = start
        next_heartbeat = start + PROGRESS_LOG_INTERVAL
        graph_snapshot_logged = False
        completion_was_true = False
        last_rpc_error_log_ts = None
        sampling_degraded = False
        bootnode_present_was = None

        while time.monotonic() < deadline:
            if node.proc.poll() is not None:
                raise NodeExited(f"fnn exited early rc={node.proc.returncode}")
            now = time.monotonic()
            if now < next_poll:
                time.sleep(min(0.5, next_poll - now))
                continue
            next_poll = now + POLL_INTERVAL

            agg = node.read_latest_aggregate()
            if agg is not None:
                latest_agg = agg
            if node.agg_reader.ever_finished and not ever_finished:
                ever_finished = True
                first_finished_ts = time.monotonic()
                result.active_sync_finished_observed_seconds = round(
                    first_finished_ts - start, 1
                )
                _progress(
                    network,
                    "ActiveSyncingFinished observed",
                    start,
                    observed_s=result.active_sync_finished_observed_seconds,
                    aggregate_seq=node.agg_reader.seq,
                )

            try:
                # A graph scan is accepted only when it is bracketed by the same
                # peer fingerprint. Otherwise graph + aggregate may describe
                # different generations, so discard the whole observation.
                peers_before = node.list_peers(deadline)
                peer_fp_before = _peer_fingerprint(peers_before)
                nodes, n_scan = node.paginate(
                    "graph_nodes", "nodes", deadline, _merge_node
                )
                channels, c_scan = node.paginate(
                    "graph_channels", "channels", deadline, _merge_channel
                )
                # Keep orchestration fail-closed even if paginate is replaced by a
                # test double or future implementation that omits validation.
                for graph_node in nodes:
                    _validate_node_item(graph_node)
                for graph_channel in channels:
                    _validate_channel_item(graph_channel)
                peers_after = node.list_peers(deadline)
                peer_fp_after = _peer_fingerprint(peers_after)
            except DeadlineExceeded:
                _progress(network, "hard deadline reached during graph scan", start)
                break
            except (
                requests.exceptions.RequestException,
                RuntimeError,
                ValueError,
            ) as e:
                # A failed observation breaks the stable window: only fully
                # successful samples may accumulate toward STABLE_WINDOW, so a
                # 35 s RPC outage can never be counted as 35 s of "stable".
                completion_since = None
                completion_was_true = False
                last_successful_sample_ts = None
                sampling_degraded = True
                error_now = time.monotonic()
                if (
                    last_rpc_error_log_ts is None
                    or error_now - last_rpc_error_log_ts >= PROGRESS_LOG_INTERVAL
                ):
                    _progress(
                        network,
                        "graph observation failed; stability window reset",
                        start,
                        error=type(e).__name__,
                    )
                    last_rpc_error_log_ts = error_now
                continue

            if peer_fp_before != peer_fp_after:
                if prev_peer_fp is not None and prev_peer_fp != peer_fp_before:
                    peer_set_changes += 1
                peer_set_changes += 1
                prev_peer_fp = peer_fp_after
                peer_change_seq = node.agg_reader.seq
                completion_since = None
                completion_was_true = False
                last_successful_sample_ts = None
                _progress(
                    network,
                    "peer set changed during graph scan; sample discarded",
                    start,
                    peers_before=len(peer_fp_before),
                    peers_after=len(peer_fp_after),
                    peer_set_changes=peer_set_changes,
                )
                continue

            if sampling_degraded:
                _progress(network, "graph observation recovered", start)
                sampling_degraded = False
                last_rpc_error_log_ts = None

            peers = peers_after
            peers_len = len(peers)
            matched_now = node.match_bootnodes(peers)
            if matched_now and not bootnode_seen:
                bootnode_seen = True
                result.bootnodes_matched = matched_now
                _progress(
                    network,
                    "configured bootnode connected",
                    start,
                    matched=len(matched_now),
                    peers=peers_len,
                )
            elif bootnode_present_was is True and not matched_now:
                _progress(
                    network,
                    "configured bootnode disconnected; stability window reset",
                    start,
                    peers=peers_len,
                )
            elif bootnode_present_was is False and matched_now:
                _progress(
                    network,
                    "configured bootnode reconnected",
                    start,
                    matched=len(matched_now),
                    peers=peers_len,
                )
            bootnode_present_was = bool(matched_now)

            # peer-generation gate: bind completion to the CURRENT bootnode-driven
            # peer set. list_peers alone cannot prove a same-pubkey reconnect is the
            # same session, so instead of claiming session identity we (a) fingerprint
            # the peer set (pubkey+address) and reset the window whenever it changes,
            # and (b) require a *fresh* aggregate line emitted AFTER that change, so a
            # stale aggregate describing an old (equal-count) peer set can't pass.
            peer_fp = peer_fp_after
            if peer_fp != prev_peer_fp:
                if prev_peer_fp is not None:
                    peer_set_changes += 1
                    _progress(
                        network,
                        "peer set changed; stability window reset",
                        start,
                        peers=peers_len,
                        peer_set_changes=peer_set_changes,
                    )
                prev_peer_fp = peer_fp
                completion_since = None
                completion_was_true = False
                peer_change_seq = node.agg_reader.seq

            # exclude our own node from the node count
            self_pk = (self_pubkey or "").lower()
            n = sum(1 for x in nodes if (x.get("pubkey") or "").lower() != self_pk)
            c = len(channels)
            sample_ts = time.monotonic()
            sample_gap = (
                sample_ts - last_successful_sample_ts
                if last_successful_sample_ts is not None
                else None
            )
            if _sample_gap_exceeded(last_successful_sample_ts, sample_ts):
                # A long scan or scheduler pause creates an observation hole. It
                # cannot count as proof that the graph was stable throughout.
                completion_since = None
                completion_was_true = False
                _progress(
                    network,
                    "observation gap exceeded; stability window reset",
                    start,
                    gap_s=round(sample_gap, 1),
                    max_gap_s=MAX_SAMPLE_GAP,
                )
            last_successful_sample_ts = sample_ts

            count = (n, c)
            digest = (_nodes_digest(nodes, self_pubkey), _channels_digest(channels))
            count_changed = prev_count is None or count != prev_count
            digest_changed = prev_digest is None or digest != prev_digest
            graph_changed_after_finish = (
                ever_finished and prev_digest is not None and digest_changed
            )
            if count_changed:
                last_count_change_ts = sample_ts
            if digest_changed:
                last_digest_change_ts = sample_ts
            prev_count, prev_digest = count, digest

            if not graph_snapshot_logged:
                graph_snapshot_logged = True
                _progress(
                    network,
                    "first graph snapshot",
                    start,
                    peers=peers_len,
                    nodes=n,
                    channels=c,
                )
            elif graph_changed_after_finish:
                _progress(
                    network,
                    "graph changed after active sync; stability window reset",
                    start,
                    nodes=n,
                    channels=c,
                    cardinality_changed=count_changed,
                )

            current_complete = (
                latest_agg is not None and latest_agg.all_connected_finished
            )
            peers_count_match = latest_agg is not None and latest_agg.total == peers_len
            fresh_aggregate = node.agg_reader.seq > peer_change_seq
            current_bootnode_present = bool(matched_now)
            remote_nonempty = n > 0 and c > 0
            completion = (
                ever_finished
                and current_complete
                and peers_count_match
                and fresh_aggregate
                and current_bootnode_present
                and remote_nonempty
            )
            if completion:
                if completion_since is None:
                    completion_since = sample_ts
                    _progress(
                        network,
                        "completion conditions satisfied; waiting for graph stability",
                        start,
                        nodes=n,
                        channels=c,
                        stable_window_s=STABLE_WINDOW,
                    )
            else:
                if completion_was_true:
                    _progress(
                        network,
                        "completion conditions lost; stability window reset",
                        start,
                    )
                completion_since = None
            completion_was_true = completion

            result.samples.append(
                {
                    "t": round(sample_ts - start, 1),
                    "nodes": n,
                    "channels": c,
                    "nodes_digest": digest[0][:12],
                    "channels_digest": digest[1][:12],
                    "n_scan_s": n_scan,
                    "c_scan_s": c_scan,
                    "agg": asdict(latest_agg) if latest_agg else None,
                    "agg_seq": node.agg_reader.seq,
                    "peers": peers_len,
                    "peer_set_size": len(peer_fp),
                    "bootnode_now": current_bootnode_present,
                    "fresh_aggregate": fresh_aggregate,
                    "completion": completion,
                }
            )

            anchor = max(
                last_count_change_ts,
                last_digest_change_ts,
                completion_since or sample_ts,
            )
            graph_stable = (sample_ts - anchor) >= STABLE_WINDOW

            if sample_ts >= next_heartbeat:
                stable_for = round(max(0.0, sample_ts - anchor), 1) if completion else 0
                aggregate = (
                    (
                        f"finished:{latest_agg.finished},"
                        f"active:{latest_agg.active},"
                        f"passive:{latest_agg.passive},"
                        f"total:{latest_agg.total}"
                    )
                    if latest_agg
                    else "unavailable"
                )
                _progress(
                    network,
                    "progress",
                    start,
                    peers=peers_len,
                    nodes=n,
                    channels=c,
                    aggregate=aggregate,
                    stable_for_s=stable_for,
                )
                next_heartbeat = sample_ts + PROGRESS_LOG_INTERVAL

            if completion and graph_stable:
                if node.proc.poll() is not None:
                    raise NodeExited(
                        f"fnn exited during final graph scan rc={node.proc.returncode}"
                    )
                result.converged = True
                result.converged_observed_seconds = round(sample_ts - start, 1)
                result.node_count = n
                result.channel_count = c
                result.peers_final = peers_len
                result.nodes_digest, result.channels_digest = digest
                result.graph_cardinality_last_change_seconds = round(
                    last_count_change_ts - start, 1
                )
                result.last_digest_change_seconds = round(
                    last_digest_change_ts - start, 1
                )
                result.final_sync_aggregate = asdict(latest_agg)
                result.bootnode_seen = bootnode_seen
                _progress(
                    network,
                    "graph stability window satisfied; finalizing attempt",
                    start,
                    active_sync_finished_s=(
                        result.active_sync_finished_observed_seconds
                    ),
                    last_digest_change_s=result.last_digest_change_seconds,
                    sync_duration_s=result.converged_observed_seconds,
                    nodes=n,
                    channels=c,
                    stable_window_s=STABLE_WINDOW,
                )
                break

        result.peer_set_changes = peer_set_changes
        result.final_aggregate_seq = node.agg_reader.seq

        if not result.converged:
            # fill best-effort diagnostics for the report
            result.node_count = prev_count[0] if prev_count else 0
            result.channel_count = prev_count[1] if prev_count else 0
            result.peers_final = peers_len
            if prev_digest:
                result.nodes_digest, result.channels_digest = prev_digest
            result.graph_cardinality_last_change_seconds = round(
                last_count_change_ts - start, 1
            )
            result.last_digest_change_seconds = round(last_digest_change_ts - start, 1)
            result.final_sync_aggregate = asdict(latest_agg) if latest_agg else None
            result.bootnode_seen = bootnode_seen
            result.failure_reason = _diagnose_failure(
                ever_finished, latest_agg, bootnode_seen, peers_len, prev_count
            )
            # a soft timeout (didn't converge in the budget) is a transient public
            # -network condition, so a single retry is allowed.
            result.retryable = True
    except Exception as e:
        result.failure_reason = _safe_reason(e, ckb_url)
        result.retryable = _is_retryable(e)
    finally:
        # Stop the sync clock before shutdown: process teardown is operational
        # overhead, not graph-sync duration.
        sync_end = time.monotonic()
        if start is not None:
            result.sync_seconds = round(sync_end - start, 1)

        stop_failed = False
        if node is not None:
            # Lifecycle order: stop -> unlink BOTH secret locations -> measure and
            # bounded-archive log -> clean -> write summary LAST.
            st0 = time.monotonic()
            try:
                node.stop()
            except Exception as e:
                stop_failed = True
                _record_cleanup_failure(result, _safe_reason(e, ckb_url))
            result.stop_seconds = round(time.monotonic() - st0, 3)

            try:
                node.shred_secret()
            except Exception as e:
                _record_cleanup_failure(result, _safe_reason(e, ckb_url))

            log_size = None
            try:
                if os.path.exists(node.log_path):
                    log_size = os.path.getsize(node.log_path)
                    result.node_log_bytes = log_size
            except OSError as e:
                _record_artifact_failure(result, _safe_reason(e, ckb_url))
            result.node_log_capped = node.agg_reader.capped or (
                log_size is not None and log_size > MAX_NODE_LOG_BYTES
            )
            if log_size is not None:
                try:
                    node.archive_log(report_dir, snapshot_size=log_size)
                except Exception as e:
                    result.node_log_capped = result.node_log_capped or isinstance(
                        e, NodeLogError
                    )
                    _record_artifact_failure(result, _safe_reason(e, ckb_url))

            # A process that survived SIGKILL keeps its work dir for local
            # diagnosis. Otherwise always clean it, even if explicit key unlink
            # failed: recursive removal is the second line of defence.
            if not stop_failed:
                try:
                    node.clean()
                except Exception as e:
                    _record_cleanup_failure(result, _safe_reason(e, ckb_url))
        elif work_dir is not None:
            # DailySyncNode construction can fail (for example while reserving an
            # RPC port). No node exists to own cleanup in that path.
            try:
                shutil.rmtree(work_dir)
            except OSError as e:
                _record_cleanup_failure(result, _safe_reason(e, ckb_url))

        # Structured artifacts are part of the terminal outcome too. Write them
        # before the final status line so a disk/write failure can never leave a
        # misleading PASS in the live CI log.
        _write_result_files(report_dir, result)

        if result.converged:
            _progress(
                network,
                "PASS graph sync converged",
                start,
                sync_duration_s=result.converged_observed_seconds,
                active_sync_finished_s=result.active_sync_finished_observed_seconds,
                last_digest_change_s=result.last_digest_change_seconds,
                cleanup="ok",
                artifacts="ok",
                samples=len(result.samples),
                node_log_bytes=result.node_log_bytes,
                stop_s=result.stop_seconds,
            )
        else:
            _progress(
                network,
                "attempt failed",
                start,
                retryable=result.retryable,
                cleanup="failed" if result.cleanup_failure else "ok",
                artifacts="failed" if result.artifact_failure else "ok",
                reason=result.failure_reason or "unknown",
            )
    return result


def _diagnose_failure(ever_finished, latest_agg, bootnode_seen, peers_len, prev_count):
    reasons = []
    if not bootnode_seen:
        reasons.append("no configured bootnode appeared in list_peers")
    if not ever_finished:
        reasons.append(
            "aggregate finished>0 never observed (no active-sync completion)"
        )
    elif latest_agg is not None and not latest_agg.all_connected_finished:
        reasons.append(
            f"connected peers still syncing (agg total={latest_agg.total} "
            f"finished={latest_agg.finished} active={latest_agg.active} "
            f"passive={latest_agg.passive})"
        )
    if latest_agg is not None and latest_agg.total != peers_len:
        reasons.append(
            f"aggregate/peer-set mismatch (agg total={latest_agg.total}, "
            f"list_peers={peers_len})"
        )
    if prev_count and not (prev_count[0] > 0 and prev_count[1] > 0):
        reasons.append(
            f"remote graph empty (nodes={prev_count[0]}, channels={prev_count[1]})"
        )
    if not reasons:
        reasons.append("counts did not stabilize before the hard deadline")
    return "; ".join(reasons)


def resolve_config_path(network, explicit=None):
    """Locate the official config: explicit path wins, else the cloned fiber source."""
    if explicit:
        return explicit
    from framework.util import get_project_root

    candidate = os.path.join(
        get_project_root(), "fiber", "config", network, "config.yml"
    )
    if os.path.exists(candidate):
        return candidate
    raise FileNotFoundError(
        f"official {network} config not found at {candidate}; "
        f"set DAILY_SYNC_CONFIG or build fiber first (BuildFIBER=true)"
    )


def resolve_fnn_path(explicit=None):
    if explicit:
        return explicit
    from framework.util import get_project_root

    candidate = os.path.join(get_project_root(), "download", "fiber", "current", "fnn")
    if os.path.exists(candidate):
        return candidate
    raise FileNotFoundError(
        f"fnn binary not found at {candidate}; set DAILY_SYNC_FNN or build fiber first"
    )
