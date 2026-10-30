"""Exact single-TLC ledger for the approved 04c2064 refund lifecycle."""

import copy
import json
import subprocess
from fractions import Fraction

from test_cases.fiber.devnet.lsp._lsp_test import BUNDLE
from test_cases.fiber.devnet.lsp.test_watchtower_settlement import digest, number, raw


def epoch_fraction(value):
    value = number(value)
    n, i, length = value & 0xFFFFFF, (value >> 24) & 0xFFFF, (value >> 40) & 0xFFFF
    assert length > 0 and i < length, "invalid epoch fraction"
    return Fraction(n * length + i, length)


def witness_layout(args):
    assert len(args) in (57, 58), "unsupported commitment lock args"
    features = args[57] if len(args) == 58 else 0
    assert features in (0, 1), "unsupported commitment feature bitmap"
    return 32 if features & 1 else 20


class RefundLedger:
    def verify_commitment(self, tx):
        """Bind the canonical close to the verified remote snapshot and opening."""
        tenant = self.a
        assert self.transaction(tx["hash"]) == tx
        assert len(tx["inputs"]) == len(tx["outputs"]) == 1
        assert tx["inputs"][0]["previous_output"] == tenant["funding"]
        assert tx["cell_deps"] == tenant["deps"]["funding_deps"]
        assert tx["outputs"][0]["type"] is None and tx["outputs_data"] == ["0x"]
        message = subprocess.check_output(
            [str(BUNDLE / "lsp-integration-driver"), "commitment-message"],
            input=json.dumps({k: v for k, v in tx.items() if k != "hash"}),
            text=True,
            timeout=10,
        ).strip()
        matches = [r for r in tenant["records"] if r["reference"]["tx_hash"] == message]
        assert len(matches) == 1, (message, matches)
        source = matches[0]
        assert source["reference"]["for_remote"] is True
        assert len(source["tlcs"]) == 1
        tlc = source["tlcs"][0]
        assert tlc["payment_hash"] == self.payment_hash
        assert tlc["hash_algorithm"] == "sha256" and tlc["inbound"] is False
        assert number(tlc["payment_amount"]) == self.amount == 100000000
        assert number(tlc["expiry"]) == self.expiry_ms
        assert tlc["local_key_commitment_number"] is not None
        args = raw(tx["outputs"][0]["lock"]["args"])
        hlen = witness_layout(args)
        assert source["payment_hash_len"] == hlen
        body, entry = raw(source["witness"]), raw(tlc["entry"])
        assert len(body) == 1 + 65 + hlen + 72 and body[0] == 1
        assert len(entry) == 65 + hlen and body[1 : 1 + len(entry)] == entry
        # A's offered TLC, viewed in A's for_remote record: SHA-256/Offered.
        assert entry[0] == 2
        assert int.from_bytes(entry[1:17], "little") == self.amount
        assert entry[17 : 17 + hlen] == raw(self.payment_hash)[:hlen]
        assert len(raw(self.payment_hash)) == 32
        assert entry[17 + hlen : 37 + hlen] == digest(raw(tlc["remote_key"]))[:20]
        assert entry[37 + hlen : 57 + hlen] == digest(raw(tlc["local_key"]))[:20]
        expiry_since = int.from_bytes(entry[-8:], "little")
        assert expiry_since == (0x4000000000000000 | (self.expiry_ms // 1000))
        assert digest(body)[:20] == args[36:56] and args[56] == 0
        balances = body[1 + len(entry) :]
        assert balances[:20] == digest(raw(source["remote_key"]))[:20]
        assert balances[36:56] == digest(raw(source["local_key"]))[:20]
        ma, mt = number(source["local_amount"]), number(source["remote_amount"])
        assert int.from_bytes(balances[20:36], "little") == mt
        assert int.from_bytes(balances[56:72], "little") == ma
        params = tenant["opening"]["parameters"]
        assert (
            ma
            == number(tenant["baseline"]["local_balance"])
            + params["local_reserved_ckb_amount"]
            - self.amount
        )
        assert (
            mt
            == number(tenant["baseline"]["remote_balance"])
            + params["remote_reserved_ckb_amount"]
        )
        funding = self.transaction(tenant["funding"]["tx_hash"])
        cf = number(funding["outputs"][number(tenant["funding"]["index"])]["capacity"])
        c0 = number(tx["outputs"][0]["capacity"])
        assert ma + mt + self.amount == cf
        close_fee = cf - c0
        assert close_fee >= 0 and close_fee == params["commitment_fee"]
        # Opening helper computes this approved fee from the actual commitment size.
        rate = 1000  # opening driver independently requires negotiated rate == 1000
        assert close_fee == (self.inspect(tx)["size"] * rate + 999) // 1000
        assert ma > close_fee and mt > close_fee
        tenant.update(
            source=source, commitment=tx, funding_capacity=cf, close_fee=close_fee
        )
        self.record(
            "refund-commitment",
            source=source,
            transaction=tx,
            signing_message=message,
            M_A=ma,
            M_T=mt,
            Q=self.amount,
            C_fund=cf,
            C0=c0,
            F_close=close_fee,
        )
        return source

    def refund_signature(self, tx, unlock, fee, key_purpose, key):
        """Return exact R/S/Applied evidence for A's confirmed signature."""
        audits = self.a["gate"].audit_snapshot()["requests"]
        matches = [
            a["params"]
            for a in audits
            if a["method"] == "submit_watchtower_signature"
            and (a.get("reply") or {}).get("result", {}).get("type") == "Applied"
            and raw(a["params"]["signature"]) == unlock[2:67]
        ]
        assert matches, "A signature must be genuinely Applied and used on chain"
        submission = matches[0]
        request_id = submission["request_id"]
        status = self.requests_seen.get(request_id)
        if status is None:
            candidates = [
                (a.get("reply") or {}).get("result", {}).get("status", {})
                for a in audits
            ]
            status = next(
                (s for s in candidates if s.get("request_id") == request_id), None
            )
        assert status, "missing original R for confirmed A signature"
        content = status["content"]
        assert content["key_purpose"] == key_purpose
        checked = self.inspect(content["transaction"], submission["signature"])
        assert checked["request_id"] == request_id and checked["recovered_key"] == key
        assert {
            k: v for k, v in content["transaction"].items() if k != "witnesses"
        } == {k: v for k, v in tx.items() if k not in ("witnesses", "hash")}
        template = raw(content["transaction"]["witnesses"][0])
        actual = raw(tx["witnesses"][0])
        assert template[:-65] == actual[:-65] and template[-65:] == bytes(65)
        authorizations = [
            json.loads(line)
            for line in self.a["status_file"]
            .with_name("independent-chain.jsonl")
            .read_text()
            .splitlines()
        ]
        authorizations = [
            a
            for a in authorizations
            if a.get("request_id") == request_id and "authorization" in a
        ]
        assert authorizations and all(
            number(a["authorization"]["fee"]) == fee for a in authorizations
        )
        return {
            "R": status,
            "S": submission,
            "Applied": True,
            "inspection": checked,
            "authorizations": authorizations,
        }

    def refund_maturity(self, tx, point, args, tlc_unlock, require_expiry):
        """Check the actual confirmed input against its own canonical epochs/time."""
        included = self.rpc("get_transaction", [tx["hash"]])["tx_status"]
        header = self.rpc("get_header", [included["block_hash"]])
        assert (
            self.rpc("get_header_by_number", [header["number"]])["hash"]
            == header["hash"]
        )
        median = number(self.rpc("get_block_median_time", [header["parent_hash"]]))
        if require_expiry:
            assert median // 1000 > self.expiry_ms // 1000
        for item in tx["inputs"][1:]:
            sponsor_since = number(item["since"])
            assert sponsor_since == 0 or sponsor_since >> 56 == 0x40
            if sponsor_since:
                assert median // 1000 >= sponsor_since & 0x00FFFFFFFFFFFFFF
        actual = number(tx["inputs"][0]["since"])
        if args[56] == 0:
            required = int.from_bytes(args[20:28], "little")
            assert required >> 56 == actual >> 56 == 0xA0
            assert epoch_fraction(actual) >= epoch_fraction(required) * (
                Fraction(2, 3) if tlc_unlock else 1
            )
            origin_status = self.rpc("get_transaction", [point["tx_hash"]])["tx_status"]
            origin = self.rpc("get_header", [origin_status["block_hash"]])
            assert (
                self.rpc("get_header_by_number", [origin["number"]])["hash"]
                == origin["hash"]
            )
            assert epoch_fraction(header["epoch"]) >= epoch_fraction(
                origin["epoch"]
            ) + epoch_fraction(actual)
        else:
            assert args[56] == 1 and actual == 0
        return {
            "header": header,
            "parent_median_ms": median,
            "first_since": hex(actual),
        }

    def refund_ledger(self):
        tenant, source = self.a, self.a["source"]
        initial = raw(source["witness"])
        original = tenant["commitment"]["outputs"][0]
        hlen = witness_layout(raw(original["lock"]["args"]))
        entry_len = 65 + hlen
        tlc = source["tlcs"][0]
        point = {"tx_hash": tenant["commitment"]["hash"], "index": "0x0"}
        expected_body, rows, sides, refunded = initial, [], [], False
        complete, branch = False, None
        while len(rows) < 3:
            tx = self.spend(point)
            if tx is None:
                break
            assert tx["cell_deps"] == tenant["deps"]["settlement_deps"]
            assert tx["inputs"][0]["previous_output"] == point
            points = [
                (i["previous_output"]["tx_hash"], number(i["previous_output"]["index"]))
                for i in tx["inputs"]
            ]
            assert len(set(points)) == len(points), "duplicate input"
            parent = self.transaction(point["tx_hash"])["outputs"][
                number(point["index"])
            ]
            args, w = raw(parent["lock"]["args"]), raw(tx["witnesses"][0])
            assert witness_layout(args) == hlen
            assert w[:17] == bytes([16, 0, 0, 0] * 4 + [1])
            count = w[17]
            body_len = 1 + count * entry_len + 72
            body, unlock = w[17 : 17 + body_len], w[17 + body_len :]
            assert body == expected_body and digest(body)[:20] == args[36:56]
            assert (
                len(unlock) == 67 and unlock[1] == 0
            ), "no preimage or alternate unlock allowed"
            balances = body[1 + count * entry_len :]
            next_body = bytearray(body)
            side, final = None, False
            if unlock[0] < 254:
                assert unlock[0] == 0 and count == 1 and not rows and not refunded
                assert body[1 : 1 + entry_len] == raw(tlc["entry"])
                del next_body[1 : 1 + entry_len]
                next_body[0] = 0
                refunded, is_a, expected_p = True, True, self.amount
                purpose = {
                    "type": "Tlc",
                    "commitment_number": hex(
                        number(tlc["local_key_commitment_number"])
                    ),
                }
                key = tlc["local_key"]
                assert any(
                    number(i["since"]) >> 56 == 0x40
                    and (number(i["since"]) & 0x00FFFFFFFFFFFFFF)
                    >= self.expiry_ms // 1000
                    for i in tx["inputs"]
                )
            else:
                side = unlock[0] - 254
                assert side in (0, 1) and side not in sides
                offset = 36 * side
                assert balances[offset : offset + 20] != bytes(20)
                final = balances[36 * (1 - side) : 36 * (1 - side) + 20] == bytes(20)
                is_a = side == int(source["reference"]["for_remote"])
                if count:
                    assert count == 1 and body[1 : 1 + entry_len] == raw(tlc["entry"])
                    assert (not is_a and not rows) or (is_a and final and sides == [0])
                next_body[
                    1 + count * entry_len + offset : 1 + count * entry_len + offset + 36
                ] = bytes(36)
                expected_p = (
                    number(parent["capacity"])
                    if final
                    else int.from_bytes(balances[offset + 20 : offset + 36], "little")
                )
                purpose, key = {"type": "Settlement"}, source["local_key"]
                sides.append(side)
            sponsor, dest, rem, next_point = 0, 0, 0, None
            for i in tx["inputs"][1:]:
                prev = self.transaction(i["previous_output"]["tx_hash"])
                idx = number(i["previous_output"]["index"])
                cell = prev["outputs"][idx]
                assert (
                    cell["lock"] == self.destination
                    and cell["type"] is None
                    and prev["outputs_data"][idx] == "0x"
                )
                sponsor += number(cell["capacity"])
            assert len(tx["outputs"]) == len(tx["outputs_data"])
            for index, out in enumerate(tx["outputs"]):
                assert out["type"] is None and tx["outputs_data"][index] == "0x"
                assert (
                    number(out["capacity"])
                    >= (41 + len(raw(out["lock"]["args"]))) * 100000000
                )
                if out["lock"] == self.destination:
                    dest += number(out["capacity"])
                else:
                    assert next_point is None and index == 0 and not final
                    expected = copy.deepcopy(parent["lock"])
                    expected["args"] = (
                        "0x"
                        + (
                            args[:36] + digest(next_body)[:20] + b"\x01" + args[57:]
                        ).hex()
                    )
                    assert out["lock"] == expected
                    rem = number(out["capacity"])
                    next_point = {"tx_hash": tx["hash"], "index": hex(index)}
            assert (next_point is None) == final
            c = number(parent["capacity"])
            fee, payout = c + sponsor - rem - dest, c - rem
            assert 0 <= fee <= 10000 and payout == expected_p
            assert payout == dest - sponsor + fee
            assert dest > 0
            maturity = self.refund_maturity(
                tx, point, args, side is None, bool(count and (is_a or final))
            )
            evidence = (
                self.refund_signature(tx, unlock, fee, purpose, key) if is_a else None
            )
            # T also has an actual recoverable signature matching its settlement key.
            if not is_a:
                assert (
                    self.inspect(tx, "0x" + unlock[2:].hex())["recovered_key"]
                    == source["remote_key"]
                )
            rows.append(
                {
                    "tx_hash": tx["hash"],
                    "source": point,
                    "transaction": tx,
                    "side": side,
                    "kind": "Q" if side is None else ("A" if is_a else "T"),
                    "a": is_a,
                    "tlc": side is None,
                    "final": final,
                    "C": c,
                    "S": sponsor,
                    "R": rem,
                    "O": dest,
                    "D": dest,
                    "F": fee,
                    "P": payout,
                    "signature": evidence,
                    "maturity": maturity,
                }
            )
            expected_body = bytes(next_body)
            if final:
                complete = True
                branch = (
                    "independent-tlc-then-" + ("A-T" if sides == [1, 0] else "T-A")
                    if refunded
                    else "T-then-A-sweep"
                )
                break
            point = next_point
        if not complete and len(rows) == 3:
            raise AssertionError("fourth commitment spend or unclosed third descendant")
        if complete:
            assert sorted(sides) == [0, 1]
            assert refunded or (len(rows) == 2 and sides == [0, 1])
            assert sum(r["P"] for r in rows) == number(original["capacity"])
            assert (
                sum(r["O"] - r["S"] + r["F"] for r in rows) + tenant["close_fee"]
                == tenant["funding_capacity"]
            )
            assert sum(r["tlc"] for r in rows) == int(refunded)
            ma, mt = number(source["local_amount"]), number(source["remote_amount"])
            assert sum(r["P"] for r in rows if r["a"]) == ma + self.amount - (
                tenant["close_fee"] if rows[-1]["a"] else 0
            )
            assert sum(r["P"] for r in rows if not r["a"]) == mt - (
                tenant["close_fee"] if not rows[-1]["a"] else 0
            )
        result = {
            "rows": rows,
            "complete": complete,
            "branch": branch,
            "current": None if complete else point,
            "body": "0x" + expected_body.hex(),
        }
        self.record("refund-ledger", **result)
        return result
