"""Hash an unsigned CKB funding proposal without signing wallet inputs."""

import hashlib


def raw_transaction_hash(tx):
    """CKB Molecule RawTransaction hash; witnesses are outside the transaction ID."""

    def number(value, size=4):
        return (int(value, 16) if isinstance(value, str) else value).to_bytes(
            size, "little"
        )

    def raw(value):
        return bytes.fromhex(value.removeprefix("0x"))

    def fixed(items):
        return number(len(items)) + b"".join(items)

    def table(fields):
        offset = 4 * (len(fields) + 1)
        offsets = []
        for field in fields:
            offsets.append(number(offset))
            offset += len(field)
        return number(offset) + b"".join(offsets) + b"".join(fields)

    def outpoint(value):
        return raw(value["tx_hash"]) + number(value["index"])

    def script(value):
        args = raw(value["args"])
        return table(
            [
                raw(value["code_hash"]),
                bytes(
                    [{"data": 0, "type": 1, "data1": 2, "data2": 4}[value["hash_type"]]]
                ),
                number(len(args)) + args,
            ]
        )

    encoded = table(
        [
            number(tx["version"]),
            fixed(
                [
                    outpoint(d["out_point"])
                    + bytes([{"code": 0, "dep_group": 1}[d["dep_type"]]])
                    for d in tx["cell_deps"]
                ]
            ),
            fixed([raw(h) for h in tx["header_deps"]]),
            fixed(
                [
                    number(i["since"], 8) + outpoint(i["previous_output"])
                    for i in tx["inputs"]
                ]
            ),
            table(
                [
                    table(
                        [
                            number(o["capacity"], 8),
                            script(o["lock"]),
                            script(o["type"]) if o["type"] else b"",
                        ]
                    )
                    for o in tx["outputs"]
                ]
            ),
            table([number(len(raw(d))) + raw(d) for d in tx["outputs_data"]]),
        ]
    )
    return (
        "0x"
        + hashlib.blake2b(
            encoded, digest_size=32, person=b"ckb-default-hash"
        ).hexdigest()
    )
