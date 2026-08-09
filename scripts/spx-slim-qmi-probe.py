#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
#
# Probe the Surface Pro X ADSP SLIMbus QMI service over QRTR from userspace.
#
# This intentionally avoids the in-kernel SLIMbus controller path: no module
# unloads, no MMIO, no BAM DMA setup. It only sends QMI request packets to the
# SLIMbus control service and decodes the immediate QMI response.

import argparse
import socket
import struct
import subprocess
import sys
import time

QMI_REQUEST = 0
QMI_RESPONSE = 2

SLIMBUS_QMI_SVC_ID = 0x0301
SLIMBUS_QMI_SELECT_INSTANCE = 0x0020
SLIMBUS_QMI_POWER = 0x0021

QMI_RESULT = {
    0: "SUCCESS",
    1: "FAILURE",
}

QMI_ERROR = {
    0: "NONE",
    1: "MALFORMED_MSG",
    2: "NO_MEMORY",
    3: "INTERNAL",
    5: "CLIENT_IDS_EXHAUSTED",
    41: "INVALID_ID",
    58: "ENCODING",
    69: "DISABLED",
    90: "INCOMPATIBLE_STATE",
    94: "NOT_SUPPORTED",
}


def u8_tlv(tlv_type, value):
    return struct.pack("<BHB", tlv_type, 1, value)


def u16_tlv(tlv_type, value):
    return struct.pack("<BHH", tlv_type, 2, value)


def u32_tlv(tlv_type, value):
    return struct.pack("<BHI", tlv_type, 4, value)


def raw_tlv(tlv_type, data):
    return struct.pack("<BH", tlv_type, len(data)) + data


def qmi_msg(msg_id, txn_id, payload):
    return struct.pack("<BHHH", QMI_REQUEST, txn_id, msg_id, len(payload)) + payload


def parse_qmi_response(data):
    if len(data) < 7:
        return {"short": True, "hex": data.hex()}

    msg_type, txn_id, msg_id, msg_len = struct.unpack_from("<BHHH", data, 0)
    payload = data[7:]
    tlvs = []
    off = 0
    while off + 3 <= len(payload):
        tlv_type, tlv_len = struct.unpack_from("<BH", payload, off)
        off += 3
        val = payload[off:off + tlv_len]
        off += tlv_len
        tlvs.append((tlv_type, val))

    decoded = {
        "type": msg_type,
        "txn": txn_id,
        "msg": msg_id,
        "declared_len": msg_len,
        "actual_len": len(payload),
        "tlvs": tlvs,
        "hex": data.hex(),
    }

    for tlv_type, val in tlvs:
        if tlv_type == 0x02 and len(val) == 4:
            result, error = struct.unpack("<HH", val)
            decoded["result"] = result
            decoded["error"] = error
            decoded["result_name"] = QMI_RESULT.get(result, f"UNKNOWN_{result}")
            decoded["error_name"] = QMI_ERROR.get(error, f"UNKNOWN_{error}")

    return decoded


def discover_slim_service():
    try:
        out = subprocess.check_output(["qrtr-lookup"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return (5, 11)

    for line in out.splitlines():
        cols = line.split()
        if not cols or not cols[0].isdigit():
            continue
        service = int(cols[0])
        if service != SLIMBUS_QMI_SVC_ID:
            continue
        return (int(cols[3]), int(cols[4]))

    return (5, 11)


def open_sock(local_node):
    af = getattr(socket, "AF_QIPCRTR", 42)
    sock = socket.socket(af, socket.SOCK_DGRAM)
    sock.bind((local_node, 0))
    sock.settimeout(1.0)
    return sock


def transact(node, port, msg_id, txn_id, payload, local_node=1):
    sock = open_sock(local_node)
    msg = qmi_msg(msg_id, txn_id, payload)
    try:
        sock.sendto(msg, (node, port))
        data, addr = sock.recvfrom(4096)
        return msg, data, addr
    finally:
        sock.close()


def fmt_response(decoded):
    if decoded.get("short"):
        return f"short response: {decoded['hex']}"

    status = ""
    if "result" in decoded:
        status = f" {decoded['result_name']}/{decoded['error_name']}"
    tlv_desc = " ".join(f"tlv=0x{t:02x}:{v.hex()}" for t, v in decoded["tlvs"])
    return (
        f"type={decoded['type']} txn={decoded['txn']} msg=0x{decoded['msg']:04x} "
        f"len={decoded['actual_len']}/{decoded['declared_len']}{status} "
        f"{tlv_desc}"
    )


def select_instance_cases():
    cases = []

    for inst in (0, 1, 2, 14, 15):
        cases.append((f"select inst u32={inst}", u32_tlv(0x01, inst)))
        cases.append((f"select inst u8={inst}", u8_tlv(0x01, inst)))
        cases.append((f"select inst u16={inst}", u16_tlv(0x01, inst)))

    for inst in (0, 14):
        for mode in (1, 2):
            cases.append((
                f"select inst u32={inst} + mode tlv0x10 u32={mode}",
                u32_tlv(0x01, inst) + u32_tlv(0x10, mode),
            ))
            cases.append((
                f"select mode tlv0x10 u32={mode} + inst u32={inst}",
                u32_tlv(0x10, mode) + u32_tlv(0x01, inst),
            ))
            cases.append((
                f"select inst u8={inst} + mode tlv0x10 u8={mode}",
                u8_tlv(0x01, inst) + u8_tlv(0x10, mode),
            ))

    for tlv_type in (0x00, 0x01, 0x10):
        cases.append((f"select empty tlv0x{tlv_type:02x}", raw_tlv(tlv_type, b"")))

    return cases


def power_cases():
    cases = []
    for val in (1, 2):
        cases.append((f"power u8={val}", u8_tlv(0x01, val)))
        cases.append((f"power u32={val}", u32_tlv(0x01, val)))
        cases.append((f"power u8={val} + resp_type u32=1", u8_tlv(0x01, val) + u32_tlv(0x10, 1)))
    return cases


def run_cases(node, port, cases, msg_id, start_txn, stop_on_success):
    successes = []
    txn = start_txn
    for name, payload in cases:
        try:
            sent, resp, addr = transact(node, port, msg_id, txn, payload)
            decoded = parse_qmi_response(resp)
            ok = decoded.get("result") == 0
            print(f"\n[{txn:03d}] {name}")
            print(f"  sent: {sent.hex()}")
            print(f"  from: node={addr[0]} port={addr[1]}")
            print(f"  resp: {fmt_response(decoded)}")
            if ok:
                successes.append((name, payload, sent, decoded))
                if stop_on_success:
                    break
        except socket.timeout:
            print(f"\n[{txn:03d}] {name}")
            print("  timeout")
        except OSError as exc:
            print(f"\n[{txn:03d}] {name}")
            print(f"  socket error: {exc}")
        txn += 1
        time.sleep(0.05)
    return successes, txn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", type=int)
    parser.add_argument("--port", type=int)
    parser.add_argument("--local-node", type=int, default=1)
    parser.add_argument("--stop-on-success", action="store_true")
    parser.add_argument("--power", action="store_true", help="also probe power_req variants after select_instance")
    args = parser.parse_args()

    node, port = (args.node, args.port) if args.node is not None and args.port is not None else discover_slim_service()
    print(f"SLIMbus QMI destination: node={node} port={port}")

    successes, txn = run_cases(
        node,
        port,
        select_instance_cases(),
        SLIMBUS_QMI_SELECT_INSTANCE,
        1,
        args.stop_on_success,
    )

    if successes:
        print("\nselect_instance successes:")
        for name, payload, _sent, _decoded in successes:
            print(f"  {name}: {payload.hex()}")
    else:
        print("\nselect_instance successes: none")

    if args.power:
        print("\npower_req probes:")
        power_successes, _ = run_cases(
            node,
            port,
            power_cases(),
            SLIMBUS_QMI_POWER,
            txn + 1,
            False,
        )
        if power_successes:
            print("\npower_req successes:")
            for name, payload, _sent, _decoded in power_successes:
                print(f"  {name}: {payload.hex()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
