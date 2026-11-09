"""Shared real outbound payment preparation for PAYMENT-05 and tenant queries."""

import hashlib
import json
import os
from pathlib import Path
import re
import time

import requests

from test_cases.fiber.devnet.lsp._hosted_tenant_fixture import HostedTenantFixture
from test_cases.fiber.devnet.lsp._lsp_test import REVISION
from test_cases.fiber.devnet.lsp.test_delayed_payment_recovery import (
    _number,
    _PaymentBudgetExpired,
)

FIXED_REVISION = "76307312e8de518c9a32074e6d16867c04de4f86"


def revision_allowed(revision, retest_revision):
    return revision == FIXED_REVISION or (
        retest_revision is not None and revision == retest_revision
    )


def _payment_hash(preimage):
    return (
        "0x"
        + hashlib.blake2b(
            bytes.fromhex(preimage.removeprefix("0x")),
            digest_size=32,
            person=b"ckb-default-hash",
        ).hexdigest()
    )


def _trace_add_tlc(line):
    """Decode the pinned receiver-side AddTlc Debug, not a sender command."""
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    match = re.search(r"message: PeerMessage\(AddTlc\(AddTlc \{(.*?)\}\)\)", line)
    if match is None:
        return None
    fields = match.group(1)
    result = {}
    for key in ("channel_id", "payment_hash"):
        value = re.search(rf"\b{key}: (?:Hash256\()?((?:0x)?[0-9a-fA-F]{{64}})", fields)
        if value is None:
            raise ValueError(f"AddTlc trace missing {key}: {line}")
        result[key] = "0x" + value.group(1).removeprefix("0x").lower()
    for key in ("tlc_id", "amount", "expiry"):
        value = re.search(rf"\b{key}: (\d+)\b", fields)
        if value is None:
            raise ValueError(f"AddTlc trace missing {key}: {line}")
        result[key] = int(value.group(1))
    return result


def _active_target_tlcs(view, payment_hash):
    active = []
    for tlc in view["pending_tlcs"]:
        if tlc["payment_hash"] != payment_hash:
            continue
        status = tlc["status"]
        assert isinstance(status, dict) and len(status) == 1, status
        direction, state = next(iter(status.items()))
        assert direction in ("Inbound", "Outbound"), status
        if state != "RemoveAckConfirmed":
            active.append(tlc)
    return active


def _assert_outbound_funds(before, after, amount, upstream, fee):
    """Independent four-endpoint deltas; RPC fee is only a cross-check."""
    assert upstream == amount + fee
    deltas = {"A": -upstream, "T-A": upstream, "P": amount, "T-P": -amount}
    for key, delta in deltas.items():
        old, new = before[key], after[key]
        assert new["state"]["state_name"] == "ChannelReady", (key, new)
        assert new["channel_id"] == old["channel_id"]
        assert new["channel_outpoint"] == old["channel_outpoint"]
        assert not new["shutdown_transaction_hash"], (key, new)
        assert _number(new["local_balance"]) - _number(old["local_balance"]) == delta, (
            key,
            delta,
            old,
            new,
        )
        assert (
            _number(new["remote_balance"]) - _number(old["remote_balance"]) == -delta
        ), (key, delta, old, new)
        assert (
            _number(new["offered_tlc_balance"])
            == _number(new["received_tlc_balance"])
            == 0
        ), (key, new)
    for left, right in (("A", "T-A"), ("P", "T-P")):
        assert _number(after[left]["local_balance"]) == _number(
            after[right]["remote_balance"]
        )
        assert _number(after[left]["remote_balance"]) == _number(
            after[right]["local_balance"]
        )
    assert (
        sum(
            _number(after[k]["local_balance"]) - _number(before[k]["local_balance"])
            for k in ("T-A", "T-P")
        )
        == fee
    )


def _track_receiver_balance(history, balance, amount):
    """Validate every observed P balance, including before local fulfillment."""
    baseline = history[0]
    assert balance in (baseline, baseline + amount), (
        "unexpected receiver balance",
        history,
        balance,
    )
    if balance != history[-1]:
        assert balance > history[-1], ("receiver balance reversed", history, balance)
        history.append(balance)


class HostedOutboundFixture(HostedTenantFixture):
    tenant_labels = ("A",)
    fnn_log_level = "trace"
    runtime_prefix = "lsp-payment05-"
    evidence_prefix = "lsp-payment05-"

    def _payer_views(self, until):
        # Keep PAYMENT-05's four-role oracle: A denotes this payment's payer,
        # which can be physical tenant A or B. The full six views stay available
        # through _views for cross-tenant and cumulative checks.
        views = self._views(until)
        label = self._outbound_label
        return {
            "A": views[label],
            "T-A": views["T-" + label],
            "P": views["P"],
            "T-P": views["T-P"],
        }

    def _fail_outbound(self, kind, message, **evidence):
        self.result = kind
        self._record("payment05_failure", kind=kind, message=message, **evidence)
        raise AssertionError(f"{kind}: {message}")

    def _qualify_trace(self):
        logs = {}
        for key, fiber in (("T-A", self.fiber1), ("P", self.fiber2)):
            path = Path(fiber.tmp_path) / "node.log"
            size = path.stat().st_size
            with path.open("rb") as stream:
                stream.seek(max(0, size - 1024 * 1024))
                tail = stream.read()
            if (
                self.fnn_log_level != "trace"
                or b"Channel actor processing message:" not in tail
            ):
                self._fail_outbound(
                    "observation_limit", "receiver trace not enabled", path=str(path)
                )
            # Field qualification comes from the pinned AddTlc::Debug formatter;
            # the target payment itself must subsequently produce decodable rows.
            logs[key] = {
                "path": path,
                "offset": size,
                "channel_id": self.baseline[key]["channel_id"],
                "tlcs": {},
            }
        self._record(
            "payment05_trace_qualified",
            revision=REVISION,
            formatter="fiber-types/src/channel.rs:AddTlc::Debug",
            sources={
                k: {
                    "path": str(v["path"]),
                    "offset": v["offset"],
                    "level": "trace",
                    "channel_id": v["channel_id"],
                }
                for k, v in logs.items()
            },
        )
        return logs

    def _read_target_trace(self, logs, payment_hash):
        for key, source in logs.items():
            path = source["path"]
            if not path.exists() or path.stat().st_size < source["offset"]:
                self._fail_outbound(
                    "observation_limit",
                    "receiver log missing or truncated",
                    path=str(path),
                )
            with path.open("rb") as stream:
                stream.seek(source["offset"])
                for raw in stream:
                    if not raw.endswith(b"\n"):
                        break  # Re-read a partially written line on the next poll.
                    offset = source["offset"]
                    source["offset"] += len(raw)
                    line = raw.decode(errors="replace")
                    if (
                        "PeerMessage(AddTlc" not in line
                        or payment_hash[2:] not in line.lower()
                    ):
                        continue
                    try:
                        row = _trace_add_tlc(line)
                        if row is None:
                            raise ValueError("target AddTlc is not decodable")
                    except ValueError as error:
                        self._fail_outbound(
                            "observation_limit",
                            str(error),
                            path=str(path),
                            offset=offset,
                            raw=line,
                        )
                    if row["channel_id"] != source["channel_id"]:
                        continue
                    assert row["payment_hash"] == payment_hash, row
                    existing = source["tlcs"].get(row["tlc_id"])
                    assert existing is None or existing == row, (existing, row)
                    if existing is None:
                        source["tlcs"][row["tlc_id"]] = row
                        self._record(
                            "payment05_tlc",
                            endpoint=key,
                            path=str(path),
                            offset=offset,
                            tlc=row,
                            raw=line,
                        )

    def _outbound_sample(self, tenant, payment_hash, logs, until):
        try:
            self._read_target_trace(logs, payment_hash)
            expiries = [
                t["expiry"] for source in logs.values() for t in source["tlcs"].values()
            ]
            if expiries:
                # Same fixed devnet/SDK safety bound as the existing payment fixture
                # (1 epoch, trusted epoch duration 2000ms); no admission-delta subtraction.
                safe_wall_ms = min(expiry // 1000 * 1000 - 1334 for expiry in expiries)
                self.outbound_until = min(
                    self.outbound_until,
                    time.monotonic() + (safe_wall_ms - time.time() * 1000) / 1000,
                )
            until = min(until, self.outbound_until)
            with self._budget(until, 5):
                views = self._payer_views(until)
                payment = self._rpc(
                    tenant["client"],
                    "get_payment",
                    [{"payment_hash": payment_hash}],
                    until,
                )
                invoice = self._rpc(
                    self.fiber2.client,
                    "get_invoice",
                    [{"payment_hash": payment_hash}],
                    until,
                )
                signing = self._signing(tenant, until)
                records = self._control(tenant, "records", until)
                sample = {
                    "views": views,
                    "payment": payment,
                    "invoice": invoice,
                    "signing": signing,
                    "records": records,
                }
                finished = time.monotonic()
                previous = getattr(self, "_outbound_sample_finished", None)
                if previous is not None and finished - previous > 2:
                    self._fail_outbound(
                        "observation_limit",
                        "complete sample interval exceeded 2 seconds",
                        previous=previous,
                        finished=finished,
                    )
                self._outbound_sample_finished = finished
                sample["finished"] = finished
                self._record("payment05_sample", **sample)
                assert payment["status"] != "Failed", payment
                assert invoice["status"] not in ("Cancelled", "Expired"), invoice
                disk = os.statvfs(self.evidence_dir)
                if disk.f_bavail * disk.f_frsize < 8 * 2**30:
                    self._fail_outbound(
                        "observation_limit", "free disk fell below 8GiB"
                    )
                return sample
        except (OSError, requests.RequestException, ValueError) as error:
            self._fail_outbound(
                "observation_limit", f"observation source unavailable: {error!r}"
            )

    def _complete_outbound_payment(self, tenant):
        """
        1. 核对 A–T、T–P 四端基线和接收侧 trace 采集资格。
        2. P 创建发票，A 持久授权并经 T 发起唯一付款。
        3. 关联两段 TLC，A 从自身 RPC 取得前像后批准兑现。
        4. 核对终态资金、费用、目标 TLC 清理及至少五秒稳定。
        """
        # 1. 保存四端资金基线，发送前核对预算与 trace 资格。
        self.result = "preparation_failure"
        self._outbound_label = tenant.get("label", "A")
        audit_start = len(
            (self.evidence_dir / "observations.jsonl").read_text().splitlines()
        )
        self.__dict__.pop("_outbound_sample_finished", None)
        self._record("outbound_preparation", payer_label=self._outbound_label)
        amount, upstream, fee = 1_000_000, 1_005_000, 5_000
        self.baseline = self._payer_views(self.business_until)
        assert set(self.baseline) == {"A", "T-A", "P", "T-P"}
        for view in self.baseline.values():
            assert view["state"]["state_name"] == "ChannelReady", view
            assert (
                _number(view["offered_tlc_balance"])
                == _number(view["received_tlc_balance"])
                == 0
            )
            assert not view["pending_tlcs"] and view["channel_outpoint"]
        assert (
            self._signing(tenant, self.business_until)["type"] == "NoSignatureRequired"
        )
        logs = self._qualify_trace()
        assert (
            self.business_until - time.monotonic() >= 80
        ), "preparation left insufficient 30+45+5s budget"
        self._record(
            "payment05_baseline",
            views=self.baseline,
            amount=amount,
            expected_upstream=upstream,
            expected_fee=fee,
        )

        # 2. P 签发普通发票；A 保存 exact-amount 出站授权并只发送一次。
        preimage = self.generate_random_preimage()
        payment_hash = _payment_hash(preimage)
        invoice = self._rpc(
            self.fiber2.client,
            "new_invoice",
            [
                {
                    "amount": hex(amount),
                    "currency": "Fibd",
                    "expiry": hex(600),
                    "payment_preimage": preimage,
                    "hash_algorithm": "ckb_hash",
                    "allow_trampoline_routing": True,
                    "allow_mpp": False,
                }
            ],
            self.business_until,
        )
        assert invoice["invoice"]["data"]["payment_hash"] == payment_hash
        assert (
            self._rpc(
                self.fiber2.client,
                "get_invoice",
                [{"payment_hash": payment_hash}],
                self.business_until,
            )["status"]
            == "Open"
        )
        authorized_at = int(time.time() * 1000)
        authorization = {
            "payment_hash": payment_hash,
            "hash_algorithm": "ckb_hash",
            "inbound": False,
            "amount": upstream,
            "expires_at_ms": authorized_at + 600_000,
            "min_tlc_expiry_delta_ms": 300_000,
            "max_tlc_expiry_ms": authorized_at + 86_400_000,
        }
        assert (
            self._control(
                tenant,
                "outgoing-payment",
                self.business_until,
                {"authorization": authorization},
            )["saved"]
            is True
        )
        invoice_until_ms = _number(invoice["invoice"]["data"]["timestamp"]) + 600_000
        sent = time.monotonic()
        sent_wall_ms = int(time.time() * 1000)
        until = min(
            self.business_until,
            sent + 120,
            sent
            + (min(invoice_until_ms, authorization["expires_at_ms"]) - sent_wall_ms)
            / 1000,
        )
        assert (
            until - sent >= 80
        ), "invoice/authorization leaves insufficient observation budget"
        self._record(
            "payment05_send",
            payment_hash=payment_hash,
            new_invoice_calls=1,
            send_payment_calls=1,
            deadline=until,
        )
        result = self._rpc(
            tenant["client"],
            "send_payment",
            [
                {
                    "invoice": invoice["invoice_address"],
                    "max_fee_amount": hex(10_000),
                    "tlc_expiry_limit": hex(86_400_000),
                    "timeout": hex(120),
                    "trampoline_hops": [self.public_key],
                }
            ],
            until,
        )
        assert result["payment_hash"] == payment_hash
        self.result = "assertion_failure"
        self.outbound_until = until

        # 3. 等待实际 TLC/SDK 记录和 A 自身 RPC 的前像，不使用测试输入替代。
        fulfill_until = min(until, time.monotonic() + 30)
        receiver_balances = [_number(self.baseline["P"]["local_balance"])]
        sample = None
        try:
            while time.monotonic() < fulfill_until:
                sample = self._outbound_sample(
                    tenant, payment_hash, logs, fulfill_until
                )
                fulfill_until = min(fulfill_until, self.outbound_until)
                _track_receiver_balance(
                    receiver_balances,
                    _number(sample["views"]["P"]["local_balance"]),
                    amount,
                )
                has_record = any(
                    tlc["payment_hash"] == payment_hash
                    for record in sample["records"]
                    for tlc in record["tlcs"]
                )
                observed = sample["payment"].get("payment_preimage")
                if has_record and observed is not None:
                    assert (
                        observed == preimage and _payment_hash(observed) == payment_hash
                    )
                    break
                self._pause(fulfill_until, 0.2)
            else:
                sample = None
        except _PaymentBudgetExpired:
            if time.monotonic() < min(fulfill_until, self.outbound_until) - 0.02:
                self._fail_outbound(
                    "observation_limit",
                    "RPC/control sampling exceeded its observation cap",
                )
            sample = None
        if sample is None or not has_record or observed is None:
            accepted = bool(logs["T-A"]["tlcs"])
            self._fail_outbound(
                "assertion_failure" if accepted else "product_stall_candidate",
                "no SDK record/payer RPC preimage before the fixed deadline",
                accepted=accepted,
            )
        assert (
            self._control(
                tenant,
                "fulfill",
                self.outbound_until,
                {"payment_hash": payment_hash, "preimage": observed},
            )["saved"]
            is True
        )
        self._record(
            "payment05_fulfilled",
            payment_hash=payment_hash,
            source="tenant get_payment.payment_preimage",
        )

        # 4. 精确四端资金与目标 TLC 裁决，成功后持续至少五秒采样。
        completion_until = min(self.outbound_until, time.monotonic() + 45)
        stable_since = None
        stable_fingerprint = None
        stable_samples = 0
        try:
            while time.monotonic() < completion_until:
                sample = self._outbound_sample(
                    tenant, payment_hash, logs, completion_until
                )
                completion_until = min(completion_until, self.outbound_until)
                views = sample["views"]
                _track_receiver_balance(
                    receiver_balances, _number(views["P"]["local_balance"]), amount
                )
                active = {
                    key: _active_target_tlcs(view, payment_hash)
                    for key, view in views.items()
                }
                complete = (
                    sample["payment"]["status"] == "Success"
                    and sample["invoice"]["status"] == "Paid"
                    and not any(active.values())
                    and sample["signing"]["type"] == "NoSignatureRequired"
                )
                if complete:
                    assert (
                        logs["T-A"]["tlcs"] and logs["P"]["tlcs"]
                    ), "missing qualified two-leg TLC evidence"
                    for key, expected in (("T-A", upstream), ("P", amount)):
                        assert all(
                            t["amount"] == expected for t in logs[key]["tlcs"].values()
                        ), logs[key]
                    measured_upstream = next(iter(logs["T-A"]["tlcs"].values()))[
                        "amount"
                    ]
                    measured_received = next(iter(logs["P"]["tlcs"].values()))["amount"]
                    actual_fee = measured_upstream - measured_received
                    assert actual_fee == fee and measured_received == amount
                    _assert_outbound_funds(
                        self.baseline, views, amount, measured_upstream, actual_fee
                    )
                    assert _number(sample["payment"]["fee"]) == actual_fee
                    stable_views = {
                        key: {
                            field: view[field]
                            for field in (
                                "channel_id",
                                "channel_outpoint",
                                "state",
                                "local_balance",
                                "remote_balance",
                                "offered_tlc_balance",
                                "received_tlc_balance",
                                "shutdown_transaction_hash",
                            )
                        }
                        for key, view in views.items()
                    }
                    fingerprint = json.dumps(
                        {
                            "views": stable_views,
                            "payment": sample["payment"],
                            "invoice": sample["invoice"],
                            "signing": sample["signing"],
                        },
                        sort_keys=True,
                    )
                    if stable_since is None:
                        stable_since = sample["finished"]
                        stable_fingerprint = fingerprint
                    assert (
                        fingerprint == stable_fingerprint
                    ), "terminal payment/funds/history changed during stability observation"
                    stable_samples += 1
                    stable_seconds = sample["finished"] - stable_since
                    if stable_seconds >= 5 and stable_samples >= 3:
                        audit = [
                            json.loads(line)
                            for line in (self.evidence_dir / "observations.jsonl")
                            .read_text()
                            .splitlines()[audit_start:]
                        ]
                        assert (
                            sum(
                                row.get("stage") == "rpc"
                                and row.get("method") == "new_invoice"
                                for row in audit
                            )
                            == 1
                        )
                        assert (
                            sum(
                                row.get("stage") == "rpc"
                                and row.get("method") == "send_payment"
                                for row in audit
                            )
                            == 1
                        )
                        self._record(
                            "payment05_passed",
                            payer_label=self._outbound_label,
                            payment_hash=payment_hash,
                            amount=amount,
                            upstream=upstream,
                            fee=fee,
                            stability_seconds=stable_seconds,
                            stability_first_sample_finished=stable_since,
                            stability_last_sample_finished=sample["finished"],
                            stability_samples=stable_samples,
                            receiver_balance_changes=receiver_balances,
                            proof="derived from two-leg TLCs, exact four-endpoint deltas, cleanup and stable snapshots; not event counting",
                        )
                        return {
                            "label": self._outbound_label,
                            "hash": payment_hash,
                            "preimage": observed,
                            "amount": amount,
                            "upstream": measured_upstream,
                            "fee": actual_fee,
                            "snapshot": sample["payment"],
                            "until": self.outbound_until,
                        }
                elif stable_since is not None:
                    raise AssertionError(
                        "terminal payment regressed during stability observation"
                    )
                self._pause(completion_until, 1)
        except _PaymentBudgetExpired:
            if time.monotonic() < min(completion_until, self.outbound_until) - 0.02:
                self._fail_outbound(
                    "observation_limit",
                    "RPC/control sampling exceeded its observation cap",
                )
        self._fail_outbound(
            (
                "observation_limit"
                if stable_since is not None
                else "product_stall_candidate"
            ),
            (
                "success stability evidence incomplete"
                if stable_since is not None
                else "payment did not finish within the fixed stage deadline"
            ),
        )
