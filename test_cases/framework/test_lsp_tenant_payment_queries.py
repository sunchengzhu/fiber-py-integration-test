"""Offline regressions for actual QUERY-04/05/06 bodies and rejection layers."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import test_cases.fiber.devnet.lsp.test_tenant_payment_queries as query
import test_cases.fiber.devnet.lsp._hosted_outbound as outbound


def _views():
    return {
        key: {
            "channel_id": channel,
            "channel_outpoint": "funding-" + channel,
            "state": {"state_name": "ChannelReady"},
            "local_balance": hex(10**9),
            "remote_balance": hex(10**9),
            "offered_tlc_balance": "0x0",
            "received_tlc_balance": "0x0",
            "shutdown_transaction_hash": None,
            "pending_tlcs": [],
        }
        for key, channel in (
            ("A", "a"),
            ("T-A", "a"),
            ("B", "b"),
            ("T-B", "b"),
            ("P", "p"),
            ("T-P", "p"),
        )
    }


def _run_body(tmp_path, monkeypatch, scenario, trace, case="query04"):
    clock = [0.0]
    obj = object.__new__(query.TestTenantPaymentQueries)
    obj.tenants = [
        {
            "label": label,
            "status": {"tenant_id": "id-" + label},
            "client": SimpleNamespace(
                url="http://test.invalid/" + label,
                other_params={"Authorization": "Bearer tenant-" + label},
            ),
        }
        for label in ("A", "B")
    ]
    obj.fiber1 = SimpleNamespace(
        client=SimpleNamespace(
            url="http://test.invalid/operator",
            other_params={"Authorization": "Bearer operator"},
        )
    )
    obj.fiber2 = SimpleNamespace(client="P")
    obj.business_until = 420
    obj.evidence_dir = tmp_path
    (tmp_path / "observations.jsonl").write_text("")
    payments = {}
    for label, seed in (("A", "11"), ("B", "22")):
        preimage = "0x" + seed * 32
        payment = {
            "label": label,
            "hash": outbound._payment_hash(preimage),
            "preimage": preimage,
            "amount": 1_000_000,
            "upstream": 1_005_000,
            "fee": 5_000,
            "until": 120,
        }
        payment["snapshot"] = {
            "payment_hash": payment["hash"],
            "payment_preimage": preimage,
            "status": "Success",
            "fee": "0x1388",
            "created_at": "0x1",
            "last_updated_at": "0x2",
            "failed_error": None,
            "custom_records": None,
        }
        payments[label] = payment
    state = {
        "prepared": [],
        "matrix": False,
        "stable_count": 0,
        "before_snapshot": False,
        "owned_reads": {"A": 0, "B": 0},
        "explicit_reads": {"A": 0, "B": 0},
    }
    trace.update(
        object=obj,
        state=state,
        events=[],
        requests=[],
        target_requests=[],
        stable_times=[],
        payments=payments,
    )

    def record(stage, **values):
        trace["events"].append({"stage": stage, **values})
        with (tmp_path / "observations.jsonl").open("a") as stream:
            stream.write(json.dumps({"stage": stage, **values}) + "\n")
        if stage == f"{case}_before":
            state["before_snapshot"] = True
        if stage == f"{case}_matrix_passed":
            state["matrix"] = True
        if stage == f"{case}_stable":
            trace["stable_times"].append(values["finished"])
            state["stable_count"] += 1
            if scenario == "processing_delay" and state["stable_count"] == 3:
                clock[0] += 3.5

    def prepare(tenant):
        state["prepared"].append(tenant["label"])
        record("rpc", method="new_invoice")
        record("rpc", method="send_payment")
        return deepcopy(payments[tenant["label"]])

    def views(until):
        result = _views()
        deltas = {key: 0 for key in result}
        for label in state["prepared"]:
            deltas[label] -= 1_005_000
            deltas["T-" + label] += 1_005_000
            deltas["P"] += 1_000_000
            deltas["T-P"] -= 1_000_000
        for key, delta in deltas.items():
            result[key]["local_balance"] = hex(10**9 + delta)
            result[key]["remote_balance"] = hex(10**9 - delta)
        if scenario == "idle_tenant_changed" and state["prepared"] == ["A"]:
            result["B"]["local_balance"] = hex(10**9 + 1)
        if state["matrix"] and scenario == "fund_change":
            result["P"]["local_balance"] = hex(10**9 + 2_000_001)
        return result

    def get_payment(tenant, payment_hash, until, tenant_id=None):
        label = tenant["label"]
        trace["requests"].append((label, payment_hash))
        owner = next(k for k, p in payments.items() if p["hash"] == payment_hash)
        trace["target_requests"].append(
            {
                "caller": label,
                "hash": payment_hash,
                "tenant_id": tenant_id,
            }
        )
        if tenant_id is not None:
            target = tenant_id.removeprefix("id-")
            assert target in ("A", "B"), tenant_id
            missing = {
                "error": {"code": -32000, "message": "Payment session not found"}
            }
            if label == "operator":
                if scenario == "operator_ignores_target":
                    return {"result": deepcopy(payments[owner]["snapshot"])}
                if scenario == "operator_fixed_tenant":
                    target = "A"
                if scenario == "operator_all_missing":
                    return missing
                if target != owner:
                    if scenario == "operator_permission_error":
                        return {
                            "error": {"code": -32000, "message": "permission denied"}
                        }
                    if scenario == "operator_partial_leak":
                        missing["error"]["data"] = {
                            "fee": payments[owner]["snapshot"]["fee"]
                        }
                    return missing
                if scenario == "explicit_wrong_record":
                    owner = "B" if owner == "A" else "A"
                if scenario == "explicit_business_error":
                    return missing
                return {"result": deepcopy(payments[owner]["snapshot"])}
            if target != label:
                if scenario == "tenant_ignores_target":
                    return missing
                if scenario == "tenant_generic_denial":
                    return {"error": {"code": -32000, "message": "permission denied"}}
                if scenario == "tenant_leaked_record":
                    return {"result": deepcopy(payments[owner]["snapshot"])}
                denied = {
                    "error": {
                        "code": -32000,
                        "message": "tenant token cannot query another tenant's state",
                    }
                }
                if scenario == "tenant_partial_leak":
                    denied["error"]["data"] = {
                        "status": payments[owner]["snapshot"]["status"]
                    }
                if scenario == "tenant_malformed_denial":
                    denied["error"].pop("code")
                return denied
            state["explicit_reads"][label] += 1
            if scenario == "explicit_business_error" or (
                scenario == "explicit_reread_error"
                and state["explicit_reads"][label] == 2
            ):
                trace["fault_response"] = deepcopy(missing)
                return missing
            if scenario == "explicit_wrong_record":
                return {
                    "result": deepcopy(
                        payments["B" if label == "A" else "A"]["snapshot"]
                    )
                }
        if owner == label:
            state["owned_reads"][label] += 1
            fault_phase = {
                "owned_error_before": state["owned_reads"][label] == 1,
                "owned_error_matrix_before": state["owned_reads"][label] == 2,
                "owned_error_matrix_after": state["owned_reads"][label] == 3,
                "owned_error_stable": state["matrix"],
                "owned_malformed_error": state["matrix"],
            }
            if label == "A" and fault_phase.get(scenario, False):
                error = {
                    "code": -32000,
                    "message": f"InvalidParameter: Payment session not found: {payment_hash}",
                }
                if scenario == "owned_malformed_error":
                    error.pop("code")
                body = {"error": error}
                trace["fault_response"] = deepcopy(body)
                return body
            value = deepcopy(payments[owner]["snapshot"])
            if scenario == "wrong_positive":
                value = deepcopy(payments["B" if owner == "A" else "A"]["snapshot"])
            if scenario == "incomplete_positive":
                value.pop("created_at")
            if state["matrix"] and scenario == "history_change":
                value["last_updated_at"] = "0x3"
            return {"result": value}
        if scenario == "leaked_record":
            return {"result": deepcopy(payments[owner]["snapshot"])}
        message = (
            "permission denied"
            if scenario == "permission_error"
            else f"Payment session not found: {payment_hash}"
        )
        error = {"code": -32000, "message": message}
        if scenario == "error_data_leak":
            error["data"] = {"payment_preimage": payments[owner]["preimage"]}
        private = payments[owner]["snapshot"]
        if scenario in ("partial_status", "partial_fee", "partial_created_at"):
            field = scenario.removeprefix("partial_")
            error["data"] = {field: private[field]}
        elif scenario == "partial_metadata":
            error["data"] = {
                field: private[field] for field in ("status", "fee", "created_at")
            }
        elif scenario == "nested_partial":
            error["data"] = {
                "debug": [{"session": {"last_updated_at": private["last_updated_at"]}}]
            }
        elif scenario == "serialized_partial":
            error["data"] = json.dumps({"fee": private["fee"]})
        elif scenario == "request_hash_echo":
            error["data"] = {"params": [{"payment_hash": payment_hash}]}
        if "data" in error:
            trace["fault_response"] = {"error": deepcopy(error)}
        return {"error": error}

    obj._record = record
    obj._views = views
    obj._complete_outbound_payment = prepare
    obj._query_payment = get_payment

    def rpc(client, method, params, until):
        assert client == "P" and method == "get_invoice"
        assert params[0]["payment_hash"] in {p["hash"] for p in payments.values()}
        return {"status": "Paid"}

    obj._rpc = rpc
    obj._signing = lambda tenant, until: {"type": "NoSignatureRequired"}
    obj._pause = lambda until, seconds: clock.__setitem__(0, clock[0] + seconds)
    with monkeypatch.context() as patch:
        patch.setattr(query.time, "monotonic", lambda: clock[0])
        patch.setattr(
            query.os,
            "statvfs",
            lambda path: SimpleNamespace(f_bavail=9 * 2**30, f_frsize=1),
        )
        methods = {
            "query04": obj.test_default_payment_namespace_is_isolated,
            "query05": obj.test_explicit_payment_target_rejects_other_tenant,
            "query06": obj.test_operator_payment_query_selects_explicit_tenant,
        }
        methods[case]()


def test_query04_actual_body_accepts_valid_two_tenant_flow(tmp_path, monkeypatch):
    trace = {}
    _run_body(tmp_path, monkeypatch, "normal", trace)
    assert trace["object"].result == "passed"
    assert trace["state"]["prepared"] == ["A", "B"]
    assert len({payment_hash for _, payment_hash in trace["requests"]}) == 2
    passed = next(r for r in trace["events"] if r["stage"] == "query04_passed")
    assert (
        passed["stability_seconds"]
        == trace["stable_times"][-1] - trace["stable_times"][0]
    )
    assert passed["stability_seconds"] >= 5


@pytest.mark.parametrize(
    "scenario",
    [
        "leaked_record",
        "permission_error",
        "error_data_leak",
        "wrong_positive",
        "fund_change",
        "history_change",
        "processing_delay",
        "incomplete_positive",
        "idle_tenant_changed",
    ],
)
def test_query04_actual_body_rejects_invalid_evidence(tmp_path, monkeypatch, scenario):
    trace = {}
    with pytest.raises(AssertionError):
        _run_body(tmp_path, monkeypatch, scenario, trace)
    assert trace["object"].result != "passed"
    assert not any(r["stage"] == "query04_passed" for r in trace["events"])
    if scenario == "processing_delay":
        assert trace["stable_times"] == [0, 1, 2, 6.5]
        assert any(r.get("kind") == "observation_limit" for r in trace["events"])


@pytest.mark.parametrize("fault", ["http_auth_failure", "wrong_response_id"])
def test_native_query_uses_default_scope_and_rejects_transport_fault(
    monkeypatch, fault
):
    obj = object.__new__(query.TestTenantPaymentQueries)
    obj.business_until = query.time.monotonic() + 20
    events, requests = [], []
    obj._record = lambda stage, **values: events.append((stage, values))
    tenant = {
        "label": "B",
        "client": SimpleNamespace(
            url="http://test.invalid", other_params={"Authorization": "test-token"}
        ),
    }

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json, timeout):
            requests.append(json)
            return SimpleNamespace(
                status_code=401 if fault == "http_auth_failure" else 200,
                json=lambda: {
                    "jsonrpc": "2.0",
                    "id": (
                        json["id"] + 1 if fault == "wrong_response_id" else json["id"]
                    ),
                    "error": {"code": -32000, "message": "Payment session not found"},
                },
            )

    monkeypatch.setattr(query.requests, "Session", Session)
    with pytest.raises(AssertionError, match="observation_limit"):
        obj._query_payment(tenant, "0x" + "ab" * 32, obj.business_until)
    assert len(requests) == 1
    assert requests[0]["params"] == [{"payment_hash": "0x" + "ab" * 32}]
    assert obj.result == "observation_limit"


def test_outbound_projection_selects_physical_tenant_b():
    obj = object.__new__(query.HostedOutboundFixture)
    views = _views()
    obj._views = lambda until: views
    obj._outbound_label = "B"
    projected = obj._payer_views(1)
    assert projected["A"] is views["B"]
    assert projected["T-A"] is views["T-B"]
    assert projected["P"] is views["P"] and projected["T-P"] is views["T-P"]


@pytest.mark.parametrize(
    "scenario",
    [
        "partial_status",
        "partial_fee",
        "partial_created_at",
        "partial_metadata",
        "nested_partial",
        "serialized_partial",
    ],
)
def test_query04_rejects_partial_payment_leaks(tmp_path, monkeypatch, scenario):
    trace = {}
    with pytest.raises(AssertionError):
        _run_body(tmp_path, monkeypatch, scenario, trace)
    assert trace["state"]["prepared"] == ["A", "B"]
    assert trace["state"]["before_snapshot"]
    assert trace["object"].result == "assertion_failure"
    assert not any(r["stage"] == "query04_passed" for r in trace["events"])


@pytest.mark.parametrize(
    "scenario",
    [
        "owned_error_before",
        "owned_error_matrix_before",
        "owned_error_matrix_after",
        "owned_error_stable",
    ],
)
def test_query04_owned_payment_business_error_is_assertion_failure(
    tmp_path, monkeypatch, scenario
):
    trace = {}
    with pytest.raises(AssertionError):
        _run_body(tmp_path, monkeypatch, scenario, trace)
    assert trace["state"]["prepared"] == ["A", "B"]
    assert trace["object"].result == "assertion_failure"
    failure = next(r for r in trace["events"] if r["stage"] == "query04_failure")
    assert failure["kind"] == "assertion_failure"
    assert failure["caller"] == "A"
    assert failure["response"] == trace["fault_response"]
    assert "result" not in failure["response"]
    assert not any(r["stage"] == "query04_passed" for r in trace["events"])
    if scenario == "owned_error_stable":
        assert trace["state"]["matrix"]


def test_query04_accepts_request_hash_echo(tmp_path, monkeypatch):
    trace = {}
    _run_body(tmp_path, monkeypatch, "request_hash_echo", trace)
    assert trace["object"].result == "passed"
    assert "data" in trace["fault_response"]["error"]


def test_query04_owned_error_schema_is_observation_limit(tmp_path, monkeypatch):
    trace = {}
    with pytest.raises(AssertionError):
        _run_body(tmp_path, monkeypatch, "owned_malformed_error", trace)
    assert trace["state"]["matrix"]
    assert trace["object"].result == "observation_limit"
    assert not any(r["stage"] == "query04_passed" for r in trace["events"])


@pytest.mark.parametrize("case", ["query05", "query06"])
def test_explicit_query_actual_body_and_target_matrix(tmp_path, monkeypatch, case):
    trace = {}
    _run_body(tmp_path, monkeypatch, "normal", trace, case=case)
    assert trace["object"].result == "passed"
    assert trace["state"]["prepared"] == ["A", "B"]
    hashes = {k: p["hash"] for k, p in trace["payments"].items()}
    explicit = [r for r in trace["target_requests"] if r["tenant_id"] is not None]
    if case == "query05":
        assert [(r["caller"], r["hash"], r["tenant_id"]) for r in explicit] == [
            ("A", hashes["A"], "id-A"),
            ("A", hashes["B"], "id-B"),
            ("A", hashes["A"], "id-A"),
            ("B", hashes["B"], "id-B"),
            ("B", hashes["A"], "id-A"),
            ("B", hashes["B"], "id-B"),
        ]
    else:
        assert [(r["caller"], r["hash"], r["tenant_id"]) for r in explicit] == [
            ("operator", hashes["A"], "id-A"),
            ("operator", hashes["A"], "id-B"),
            ("operator", hashes["A"], "id-A"),
            ("operator", hashes["B"], "id-B"),
            ("operator", hashes["B"], "id-A"),
            ("operator", hashes["B"], "id-B"),
        ]
    passed = next(r for r in trace["events"] if r["stage"] == f"{case}_passed")
    assert (
        passed["stability_seconds"]
        == trace["stable_times"][-1] - trace["stable_times"][0]
    )
    assert passed["stability_seconds"] >= 5


@pytest.mark.parametrize(
    "case,scenario,kind",
    [
        ("query05", scenario, "assertion_failure")
        for scenario in (
            "tenant_ignores_target",
            "tenant_generic_denial",
            "tenant_leaked_record",
            "tenant_partial_leak",
            "explicit_business_error",
            "explicit_wrong_record",
            "explicit_reread_error",
            "fund_change",
            "history_change",
        )
    ]
    + [
        ("query05", "tenant_malformed_denial", "observation_limit"),
        ("query05", "processing_delay", "observation_limit"),
    ]
    + [
        ("query06", scenario, "assertion_failure")
        for scenario in (
            "operator_ignores_target",
            "operator_fixed_tenant",
            "operator_all_missing",
            "operator_permission_error",
            "operator_partial_leak",
            "explicit_wrong_record",
            "explicit_business_error",
            "fund_change",
            "history_change",
        )
    ]
    + [("query06", "processing_delay", "observation_limit")],
)
def test_explicit_query_actual_body_rejects_invalid_evidence(
    tmp_path, monkeypatch, case, scenario, kind
):
    trace = {}
    with pytest.raises(AssertionError):
        _run_body(tmp_path, monkeypatch, scenario, trace, case=case)
    assert trace["state"]["prepared"] == ["A", "B"]
    assert trace["object"].result == kind
    assert not any(r["stage"] == f"{case}_passed" for r in trace["events"])
    if scenario in ("fund_change", "history_change", "processing_delay"):
        assert trace["state"]["matrix"]


@pytest.mark.parametrize(
    "caller,target", [("A", None), ("B", "id-B"), ("operator", "id-A")]
)
def test_native_query_preserves_caller_target_and_original_response(
    monkeypatch, caller, target
):
    obj = object.__new__(query.TestTenantPaymentQueries)
    until = query.time.monotonic() + 10
    requests, events = [], []
    client = SimpleNamespace(
        url="http://test.invalid/" + caller,
        other_params={"Authorization": "Bearer " + caller},
    )
    response_body = {"jsonrpc": "2.0", "id": 1, "result": {"status": "Success"}}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json, timeout):
            assert self.trust_env is False
            assert 0 < timeout <= 2
            requests.append((url, headers, json))
            return SimpleNamespace(status_code=200, json=lambda: response_body)

    obj._record = lambda stage, **values: events.append(values)
    monkeypatch.setattr(query.requests, "Session", Session)
    body = obj._query_payment(
        {"label": caller, "client": client}, "H", until, tenant_id=target
    )
    assert body is response_body and len(requests) == 1
    assert requests[0][0] == client.url and requests[0][1] == client.other_params
    expected = {"payment_hash": "H"}
    if target is not None:
        expected["tenant_id"] = target
    assert requests[0][2]["params"] == [expected]
    assert events[-1]["caller"] == caller and events[-1]["response"] is response_body
    assert events[-1]["rpc_url"] == client.url
    assert (
        events[-1]["authorization_sha256"]
        == query.hashlib.sha256(
            client.other_params["Authorization"].encode()
        ).hexdigest()
    )


@pytest.mark.parametrize(
    "mode,expected_kind",
    [
        ("both_result_and_error", "observation_limit"),
        ("neither_result_nor_error", "observation_limit"),
        ("business_error", "assertion_failure"),
        ("http_failure", "observation_limit"),
    ],
)
def test_query_response_envelope_failure_attribution(
    tmp_path, monkeypatch, mode, expected_kind
):
    """Use the actual HTTP parser after valid payment preparation and query matrix."""
    cls = query.TestTenantPaymentQueries
    original_body = cls.test_default_payment_namespace_is_isolated
    trace, wire = {}, []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json, timeout):
            assert self.trust_env is False
            body = {"jsonrpc": "2.0", "id": json["id"]}
            if mode != "neither_result_nor_error":
                body["error"] = {
                    "code": -32000,
                    "message": "Payment session not found",
                }
            if mode == "both_result_and_error":
                body["result"] = deepcopy(trace["payments"]["A"]["snapshot"])
            status = 401 if mode == "http_failure" else 200
            wire.append((deepcopy(json), deepcopy(body), status))
            return SimpleNamespace(status_code=status, json=lambda: body)

    def driver(self):
        seam = self._query_payment
        fired = False

        def read(tenant, payment_hash, until, tenant_id=None):
            nonlocal fired
            if trace["state"]["matrix"] and not fired:
                fired = True
                return cls._query_payment(
                    self, tenant, payment_hash, until, tenant_id=tenant_id
                )
            return seam(tenant, payment_hash, until, tenant_id=tenant_id)

        self._query_payment = read
        return original_body(self)

    monkeypatch.setattr(cls, "test_default_payment_namespace_is_isolated", driver)
    monkeypatch.setattr(query.requests, "Session", Session)
    with pytest.raises(AssertionError):
        _run_body(tmp_path, monkeypatch, "normal", trace)
    assert trace["state"]["prepared"] == ["A", "B"]
    assert trace["state"]["matrix"] and len(wire) == 1
    assert not any(r["stage"] == "query04_passed" for r in trace["events"])
    raw = next(r for r in trace["events"] if r["stage"] == "query04_get_payment")
    assert (raw["request"], raw["response"], raw["http_status"]) == wire[0]
    assert trace["object"].result == expected_kind
    failure = next(r for r in trace["events"] if r["stage"] == "query04_failure")
    assert failure["kind"] == expected_kind
    if mode in ("both_result_and_error", "neither_result_nor_error"):
        assert failure["caller"] == "A"
        assert failure["request"] == raw["request"]
        assert failure["response"] == raw["response"]
    elif mode == "business_error":
        assert failure["response"] == raw["response"]
