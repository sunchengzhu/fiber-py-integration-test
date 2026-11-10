"""PR #1623: native payment query isolation with real A/B payments."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time

import requests

from framework.util import get_project_root
from test_cases.fiber.devnet.lsp._hosted_outbound import (
    FIXED_REVISION,
    HostedOutboundFixture,
    _active_target_tlcs,
    _number,
    _PaymentBudgetExpired,
)
from test_cases.fiber.devnet.lsp._lsp_test import REVISION
from test_cases.fiber.devnet.lsp._query_environment import QueryEnvironmentPilot


def _payment_snapshot(payment, expected):
    """Bind a fresh result to the intended real payment, not only Success."""
    required = {
        "payment_hash",
        "payment_preimage",
        "status",
        "fee",
        "created_at",
        "last_updated_at",
        "failed_error",
        "custom_records",
    }
    if not isinstance(payment, dict) or not required <= payment.keys():
        raise ValueError("payment response is incomplete")
    assert payment["payment_hash"] == expected["hash"], payment
    assert payment["status"] == "Success", payment
    assert payment["payment_preimage"] == expected["preimage"], payment
    assert _number(payment["fee"]) == expected["fee"], payment
    assert payment["failed_error"] is None, payment
    return {
        "payment_hash": payment["payment_hash"],
        "payment_preimage": payment["payment_preimage"],
        "status": payment["status"],
        "fee": _number(payment["fee"]),
        "created_at": _number(payment["created_at"]),
        "last_updated_at": _number(payment["last_updated_at"]),
        "failed_error": payment["failed_error"],
        "custom_records": payment["custom_records"],
    }


def _query_error(body):
    error = body.get("error")
    if (
        not isinstance(error, dict)
        or type(error.get("code")) is not int
        or not isinstance(error.get("message"), str)
    ):
        raise ValueError("payment error response is incomplete")
    return error


def _assert_payment_error(body, protected, reason):
    assert "result" not in body, body
    error = _query_error(body)
    assert reason in error["message"].lower(), body
    encoded = json.dumps(error).lower()
    for payment in protected.values():
        assert payment["preimage"].removeprefix("0x").lower() not in encoded, body

    # payment_hash may legitimately echo the request. Every other payment
    # result field is private even when only one field or a partial record leaks.
    private_fields = {
        "payment_preimage",
        "status",
        "fee",
        "created_at",
        "last_updated_at",
        "failed_error",
        "custom_records",
        "routers",
    }

    def has_record(value):
        if isinstance(value, dict):
            return bool(private_fields & value.keys()) or any(
                has_record(v) for v in value.values()
            )
        if isinstance(value, list):
            return any(has_record(v) for v in value)
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except ValueError:
                return False
            return decoded != value and has_record(decoded)
        return False

    assert not has_record(error), body


def _assert_payment_missing(body, protected):
    _assert_payment_error(body, protected, "payment session not found")


def _assert_tenant_target_rejected(body, protected):
    _assert_payment_error(
        body, protected, "tenant token cannot query another tenant's state"
    )
    assert "payment session not found" not in body["error"]["message"].lower(), body


def _assert_query_funds(before, after, payments):
    """Check each tenant leg and the shared P leg, including the idle tenant."""
    assert set(before) == set(after) == {"A", "T-A", "B", "T-B", "P", "T-P"}
    deltas = {key: 0 for key in before}
    for label, payment in payments.items():
        amount, upstream, fee = (
            payment["amount"],
            payment["upstream"],
            payment["fee"],
        )
        assert amount == 1_000_000 and upstream == amount + fee and fee == 5_000
        deltas[label] -= upstream
        deltas["T-" + label] += upstream
        deltas["P"] += amount
        deltas["T-P"] -= amount
    for key, delta in deltas.items():
        old, new = before[key], after[key]
        assert new["state"]["state_name"] == "ChannelReady", (key, new)
        assert new["channel_id"] == old["channel_id"], key
        assert new["channel_outpoint"] == old["channel_outpoint"], key
        assert not new["shutdown_transaction_hash"], (key, new)
        assert (
            _number(new["local_balance"]) - _number(old["local_balance"]) == delta
        ), key
        assert (
            _number(new["remote_balance"]) - _number(old["remote_balance"]) == -delta
        ), key
        assert (
            _number(new["offered_tlc_balance"])
            == _number(new["received_tlc_balance"])
            == 0
        ), key
        for payment in payments.values():
            assert not _active_target_tlcs(new, payment["hash"]), (key, new)
    for left, right in (("A", "T-A"), ("B", "T-B"), ("P", "T-P")):
        assert _number(after[left]["local_balance"]) == _number(
            after[right]["remote_balance"]
        )
        assert _number(after[left]["remote_balance"]) == _number(
            after[right]["local_balance"]
        )


class TestTenantPaymentQueries(QueryEnvironmentPilot, HostedOutboundFixture):
    tenant_labels = ("A", "B")
    runtime_prefix = "lsp-payment-query-"
    evidence_prefix = "lsp-payment-query-"

    @classmethod
    def setup_class(cls):
        assert REVISION == FIXED_REVISION, "QUERY-04/05/06 are fixed to 76307312"
        disk = os.statvfs(get_project_root())
        if disk.f_bavail * disk.f_frsize < 8 * 2**30:
            raise RuntimeError(
                "payment-query environment qualification: free disk below 8GiB"
            )
        super().setup_class()

    def _fail_query(self, kind, message, **evidence):
        self.result = kind
        self._record(
            f"{getattr(self, '_query_case', 'query04')}_failure",
            kind=kind,
            message=message,
            **evidence,
        )
        raise AssertionError(f"{kind}: {message}")

    def _query_payment(self, tenant, payment_hash, until, tenant_id=None):
        """Make one fresh native HTTP request, retaining business errors as data."""
        self._query_id = getattr(self, "_query_id", 0) + 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._query_id,
            "method": "get_payment",
            "params": [{"payment_hash": payment_hash}],
        }
        if tenant_id is not None:
            payload["params"][0]["tenant_id"] = tenant_id
        metadata = {
            "caller": tenant["label"],
            "rpc_url": tenant["client"].url,
            "authorization_sha256": hashlib.sha256(
                tenant["client"].other_params["Authorization"].encode()
            ).hexdigest(),
        }
        started = time.monotonic()
        try:
            with self._budget(until, 2) as due:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.post(
                        tenant["client"].url,
                        headers=tenant["client"].other_params,
                        json=payload,
                        timeout=max(0.001, due - time.monotonic()),
                    )
                    try:
                        body = response.json()
                    except ValueError:
                        self._record(
                            f"{getattr(self, '_query_case', 'query04')}_get_payment",
                            **metadata,
                            request=payload,
                            raw_response=response.text,
                            http_status=response.status_code,
                            started=started,
                        )
                        raise
                self._record(
                    f"{getattr(self, '_query_case', 'query04')}_get_payment",
                    **metadata,
                    request=payload,
                    response=body,
                    http_status=response.status_code,
                    started=started,
                )
                if response.status_code != 200 or not isinstance(body, dict):
                    self._fail_query(
                        "observation_limit", "invalid HTTP/JSON-RPC response"
                    )
                if body.get("jsonrpc") != "2.0" or body.get("id") != payload["id"]:
                    self._fail_query("observation_limit", "unmatched JSON-RPC response")
                if ("result" in body) == ("error" in body):
                    self._fail_query(
                        "observation_limit",
                        "invalid JSON-RPC result/error envelope",
                        caller=tenant["label"],
                        request=payload,
                        response=body,
                        http_status=response.status_code,
                    )
                return body
        except (requests.RequestException, ValueError) as error:
            self._fail_query(
                "observation_limit", f"query transport unavailable: {error!r}"
            )

    def _read_owned_payment(self, tenant, payment, until, tenant_id=None):
        # The expected record belongs to a known real payment; the caller can
        # be its tenant or an operator explicitly selecting its namespace.
        if tenant_id is None:
            body = self._query_payment(tenant, payment["hash"], until)
        else:
            body = self._query_payment(
                tenant, payment["hash"], until, tenant_id=tenant_id
            )
        if "error" in body:
            _query_error(body)  # Malformed error evidence remains an observation limit.
            self._fail_query(
                "assertion_failure",
                "owned payment query returned a business error",
                caller=tenant["label"],
                payment_hash=payment["hash"],
                response=body,
            )
        return _payment_snapshot(body["result"], payment)

    def _query_snapshot(self, payments, expected, before, until, stage):
        with self._budget(until, 5):
            histories, invoices, signing = {}, {}, {}
            for tenant in self.tenants:
                label = tenant["label"]
                histories[label] = self._read_owned_payment(
                    tenant, payments[label], until
                )
                assert histories[label] == expected[label], (
                    label,
                    histories[label],
                    expected[label],
                )
                invoices[label] = self._rpc(
                    self.fiber2.client,
                    "get_invoice",
                    [{"payment_hash": payments[label]["hash"]}],
                    until,
                )
                assert invoices[label]["status"] == "Paid", invoices[label]
                signing[label] = self._signing(tenant, until)
                assert signing[label]["type"] == "NoSignatureRequired", signing[label]
            views = self._views(until)
            _assert_query_funds(before, views, payments)
            disk = os.statvfs(self.evidence_dir)
            if disk.f_bavail * disk.f_frsize < 8 * 2**30:
                self._fail_query("observation_limit", "free disk fell below 8GiB")
            sample = {
                "histories": histories,
                "invoices": invoices,
                "signing": signing,
                "views": views,
                "finished": time.monotonic(),
            }
            self._record(stage, **sample)
            self._query_last_sample = sample
            return sample

    def _prepare_query_payments(self, case):
        """Each native method creates its own two payments and six-endpoint baseline."""
        self._query_case = case
        self.result = "preparation_failure"
        payments = {}
        before = self._views(self.business_until)
        _assert_query_funds(before, before, payments)
        assert all(not view["pending_tlcs"] for view in before.values()), before
        self._record(f"{case}_initial_funds", views=before)
        try:
            for tenant in self.tenants:
                payments[tenant["label"]] = self._complete_outbound_payment(tenant)
                _assert_query_funds(before, self._views(self.business_until), payments)
            assert len({p["hash"] for p in payments.values()}) == 2
        except BaseException:
            self._record(f"{case}_preparation_failed", underlying_result=self.result)
            self.result = "preparation_failure"
            raise
        expected = {
            label: _payment_snapshot(p["snapshot"], p) for label, p in payments.items()
        }
        self.result = "assertion_failure"
        until = min(
            self.business_until,
            time.monotonic() + 30,
            *(p["until"] for p in payments.values()),
        )
        self._query_prepared = (payments, expected)
        return payments, expected, before, until

    @contextmanager
    def _query_observation(self):
        try:
            yield
        except (
            _PaymentBudgetExpired,
            requests.RequestException,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            self._fail_query(
                "observation_limit", f"query evidence unavailable: {error!r}"
            )

    def _assert_query_stability(self, payments, expected, before, until):
        """Use complete fresh snapshots; local processing cannot fill the window."""
        first = previous = None
        count = 0
        while time.monotonic() < until:
            sample = self._query_snapshot(
                payments, expected, before, until, f"{self._query_case}_stable"
            )
            finished = sample["finished"]
            if previous is not None and finished - previous > 2:
                self._fail_query(
                    "observation_limit",
                    "complete sample interval exceeded 2 seconds",
                )
            if first is None:
                first = finished
            previous = finished
            count += 1
            if finished - first >= 5 and count >= 3:
                audit = [
                    json.loads(line)
                    for line in (self.evidence_dir / "observations.jsonl")
                    .read_text()
                    .splitlines()
                ]
                for method in ("new_invoice", "send_payment"):
                    assert (
                        sum(
                            row.get("stage") == "rpc" and row.get("method") == method
                            for row in audit
                        )
                        == 2
                    )
                self._record(
                    f"{self._query_case}_passed",
                    stability_first=first,
                    stability_last=finished,
                    stability_samples=count,
                    stability_seconds=finished - first,
                )
                self.result = "passed"
                return
            self._pause(until, 1)
        self._fail_query("observation_limit", "query stability evidence incomplete")

    # TEST-MAP: LSP-TENANT-QUERY-04
    def test_default_payment_namespace_is_isolated(self):
        """
        1. A/B 各完成一笔真实出站付款，核对单笔及累计六端资金和稳定历史。
        2. 各用自身 token 查询自己的付款成功，交叉查询返回付款不存在，再重读自身。
        3. 持续复查原付款、发票、六端资金和零锁定，确认查询无副作用。
        """
        # 1. 独立完成两笔真实付款和资金资格检查。
        payments, expected, before, until = self._prepare_query_payments("query04")
        with self._query_observation():
            self._query_snapshot(payments, expected, before, until, "query04_before")

            # 2. 默认查询不传tenant_id；每个负向都有同token的真实付款正向对照。
            for tenant in self.tenants:
                label = tenant["label"]
                other = "B" if label == "A" else "A"
                own = self._read_owned_payment(tenant, payments[label], until)
                assert own == expected[label]
                missing = self._query_payment(tenant, payments[other]["hash"], until)
                _assert_payment_missing(missing, payments)
                own_after = self._read_owned_payment(tenant, payments[label], until)
                assert own_after == expected[label]
            self._record(
                "query04_matrix_passed",
                hashes={k: p["hash"] for k, p in payments.items()},
            )

            # 3. 继续取得至少五秒的完整新样本，核对历史和六端资金无副作用。
            self._assert_query_stability(payments, expected, before, until)

    # TEST-MAP: LSP-TENANT-QUERY-05
    def test_explicit_payment_target_rejects_other_tenant(self):
        """
        1. A/B 独立完成两笔真实付款，保存所有者历史和六端资金。
        2. 各显式指定自身读取成功，指定另一租户必须因目标授权被拒，随后重读自身。
        3. 持续复查原历史、发票及六端资金，确认拒绝未产生副作用。
        """
        # 1. 使用本方法新建的付款，不依赖QUERY-04先执行。
        payments, expected, before, until = self._prepare_query_payments("query05")
        with self._query_observation():
            self._query_snapshot(payments, expected, before, until, "query05_before")

            # 2. 自身目标成功、另一目标在授权处拒绝，最后用同token显式重读自身。
            by_label = {tenant["label"]: tenant for tenant in self.tenants}
            for label, tenant in by_label.items():
                other = "B" if label == "A" else "A"
                own_id = tenant["status"]["tenant_id"]
                own = self._read_owned_payment(
                    tenant, payments[label], until, tenant_id=own_id
                )
                assert own == expected[label]
                denied = self._query_payment(
                    tenant,
                    payments[other]["hash"],
                    until,
                    tenant_id=by_label[other]["status"]["tenant_id"],
                )
                _assert_tenant_target_rejected(denied, payments)
                own_after = self._read_owned_payment(
                    tenant, payments[label], until, tenant_id=own_id
                )
                assert own_after == expected[label]
            self._record(
                "query05_matrix_passed",
                hashes={k: p["hash"] for k, p in payments.items()},
            )

            # 3. 拒绝后仍用新请求验证历史、Paid、资金、零锁定及无待签。
            self._assert_query_stability(payments, expected, before, until)

    # TEST-MAP: LSP-TENANT-QUERY-06
    def test_operator_payment_query_selects_explicit_tenant(self):
        """
        1. A/B 独立完成真实付款，保存各自成功历史和六端资金。
        2. operator按所有者目标读取成功；同一hash只改为另一目标必须返回付款不存在。
        3. 重读各所有者目标，并持续验证原历史、发票及六端资金无副作用。
        """
        # 1. 每次新建真实付款，并使用具有payments/lsp读取能力的operator。
        payments, expected, before, until = self._prepare_query_payments("query06")
        with self._query_observation():
            self._query_snapshot(payments, expected, before, until, "query06_before")
            operator = {"label": "operator", "client": self.fiber1.client}
            assert all(
                operator["client"].other_params["Authorization"]
                != tenant["client"].other_params["Authorization"]
                for tenant in self.tenants
            )

            # 2. 同operator、同hash，仅切换目标；不预设public命名空间是否有同hash。
            by_label = {tenant["label"]: tenant for tenant in self.tenants}
            for label, tenant in by_label.items():
                own_id = tenant["status"]["tenant_id"]
                other = "B" if label == "A" else "A"
                own = self._read_owned_payment(
                    operator, payments[label], until, tenant_id=own_id
                )
                assert own == expected[label]
                missing = self._query_payment(
                    operator,
                    payments[label]["hash"],
                    until,
                    tenant_id=by_label[other]["status"]["tenant_id"],
                )
                _assert_payment_missing(missing, payments)

                # 3. 错误目标之后，同operator显式重读所有者目标仍为原记录。
                own_after = self._read_owned_payment(
                    operator, payments[label], until, tenant_id=own_id
                )
                assert own_after == expected[label]
            self._record(
                "query06_matrix_passed",
                hashes={k: p["hash"] for k, p in payments.items()},
            )
            self._assert_query_stability(payments, expected, before, until)
