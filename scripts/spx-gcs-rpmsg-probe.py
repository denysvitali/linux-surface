#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
#
# Surface Pro X GCS reachability probe.
#
# This uses the upstream rpmsg char control device to create an endpoint with
# the Windows qcauddev GLINK channel name. Opening the created /dev/rpmsgN file
# asks qcom_glink_native to issue GLINK_CMD_OPEN for that channel.

import argparse
import errno
import fcntl
import os
import select
import struct
import sys
import time
from pathlib import Path

RPMSG_ADDR_ANY = 0xFFFFFFFF
RPMSG_NAME_SIZE = 32

IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14

IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS

IOC_NONE = 0
IOC_WRITE = 1


def _ioc(direction, typ, nr, size):
    return (
        (direction << IOC_DIRSHIFT)
        | (typ << IOC_TYPESHIFT)
        | (nr << IOC_NRSHIFT)
        | (size << IOC_SIZESHIFT)
    )


RPMSG_CREATE_EPT_IOCTL = _ioc(IOC_WRITE, 0xB5, 0x1, 40)
RPMSG_DESTROY_EPT_IOCTL = _ioc(IOC_NONE, 0xB5, 0x2, 0)


def rpmsg_devices():
    out = {}
    for name_file in Path("/sys/class/rpmsg").glob("rpmsg[0-9]*/name"):
        try:
            out[name_file.parent.name] = name_file.read_text().strip()
        except OSError:
            continue
    return out


def find_created(before, channel):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        after = rpmsg_devices()
        created = [
            dev for dev, name in after.items()
            if dev not in before and name == channel
        ]
        if created:
            return sorted(created, key=lambda item: int(item[5:]))[-1]

        matching = [
            dev for dev, name in after.items()
            if name == channel
        ]
        if matching:
            return sorted(matching, key=lambda item: int(item[5:]))[-1]

        time.sleep(0.05)

    return None


def create_endpoint(ctrl_dev, channel):
    raw_name = channel.encode("ascii")
    if len(raw_name) >= RPMSG_NAME_SIZE:
        raise ValueError(f"channel name is too long for rpmsg: {channel!r}")

    eptinfo = raw_name.ljust(RPMSG_NAME_SIZE, b"\0")
    eptinfo += struct.pack("II", RPMSG_ADDR_ANY, RPMSG_ADDR_ANY)

    before = rpmsg_devices()
    ctrl_fd = os.open(ctrl_dev, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(ctrl_fd, RPMSG_CREATE_EPT_IOCTL, eptinfo)
    except OSError:
        os.close(ctrl_fd)
        raise

    dev = find_created(before, channel)
    if not dev:
        os.close(ctrl_fd)
        raise RuntimeError(f"created endpoint for {channel!r}, but no /sys/class/rpmsg entry appeared")

    return ctrl_fd, Path("/dev") / dev


def hexdump(buf):
    rows = []
    for off in range(0, len(buf), 16):
        chunk = buf[off:off + 16]
        hx = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{off:04x}: {hx:<47}  {asc}")
    return "\n".join(rows)


def parse_hex(data):
    compact = "".join(data.split())
    if len(compact) % 2:
        raise ValueError("hex payload must have an even number of digits")
    return bytes.fromhex(compact)


def probe(ctrl_dev, channel, timeout, send_hex, keep):
    print(f"creating rpmsg endpoint: ctrl={ctrl_dev} channel={channel}")
    ctrl_fd, ept_dev = create_endpoint(ctrl_dev, channel)
    print(f"created endpoint: {ept_dev}")

    ept_fd = None
    try:
        print("opening endpoint; this issues the GLINK local-open request")
        ept_fd = os.open(ept_dev, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        print("open succeeded")

        if send_hex:
            payload = parse_hex(send_hex)
            print(f"sending {len(payload)} bytes")
            os.write(ept_fd, payload)

        poller = select.poll()
        poller.register(ept_fd, select.POLLIN | select.POLLPRI | select.POLLERR | select.POLLHUP)
        deadline = time.monotonic() + timeout
        seen = 0

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            events = poller.poll(remaining_ms)
            if not events:
                break

            for _, event in events:
                if event & (select.POLLERR | select.POLLHUP):
                    print(f"endpoint event: 0x{event:x}")
                    return 1
                if event & (select.POLLIN | select.POLLPRI):
                    try:
                        data = os.read(ept_fd, 4096)
                    except BlockingIOError:
                        continue
                    if not data:
                        print("read returned EOF")
                        return 1
                    seen += 1
                    print(f"rx[{seen}] {len(data)} bytes")
                    print(hexdump(data))
                    if b"READY_PKT" in data:
                        print("READY_PKT observed")

        if not seen:
            print(f"no inbound data within {timeout:.1f}s")
        return 0
    finally:
        if ept_fd is not None:
            if keep:
                print(f"leaving endpoint in place: {ept_dev}")
            else:
                try:
                    fcntl.ioctl(ept_fd, RPMSG_DESTROY_EPT_IOCTL, 0)
                except OSError as exc:
                    print(f"warning: failed to destroy endpoint: {exc}", file=sys.stderr)
                os.close(ept_fd)
        os.close(ctrl_fd)


def default_ctrl_devs():
    ctrl_devs = sorted(Path("/dev").glob("rpmsg_ctrl*"))
    if not ctrl_devs:
        return []

    def is_lpass(ctrl_dev):
        sysfs = Path("/sys/class/rpmsg") / ctrl_dev.name / "device"
        try:
            return "17300000.remoteproc" in os.path.realpath(sysfs)
        except OSError:
            return False

    lpass = [dev for dev in ctrl_devs if is_lpass(dev)]
    return lpass or ctrl_devs[:1]


def main():
    parser = argparse.ArgumentParser(description="Probe SPX qcauddev GCS GLINK reachability via rpmsg_char")
    parser.add_argument(
        "--channel",
        default="g_glink_audio_data",
        help="GLINK channel name to open; live qcauddev exposes g_glink_audio_data",
    )
    parser.add_argument(
        "--ctrl",
        help="rpmsg control device to use; defaults to the ADSP/LPASS rpmsg_ctrl if found",
    )
    parser.add_argument(
        "--all-ctrls",
        action="store_true",
        help="try every /dev/rpmsg_ctrl* instead of only the ADSP/LPASS control device",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="seconds to wait for inbound data after opening the endpoint",
    )
    parser.add_argument(
        "--send-hex",
        help="optional hex payload to send after opening; omitted by default",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the created endpoint around instead of destroying it on exit",
    )
    args = parser.parse_args()

    if args.ctrl:
        ctrl_devs = [Path(args.ctrl)]
    elif args.all_ctrls:
        ctrl_devs = sorted(Path("/dev").glob("rpmsg_ctrl*"))
    else:
        ctrl_devs = default_ctrl_devs()
    if not ctrl_devs:
        print("no /dev/rpmsg_ctrl* found; load/enable CONFIG_RPMSG_CTRL first", file=sys.stderr)
        return 1

    last_error = None
    for ctrl_dev in ctrl_devs:
        try:
            return probe(str(ctrl_dev), args.channel, args.timeout, args.send_hex, args.keep)
        except PermissionError as exc:
            last_error = exc
            print(f"{ctrl_dev}: permission denied; run as root or adjust device permissions", file=sys.stderr)
        except OSError as exc:
            last_error = exc
            if exc.errno == errno.ENODEV:
                print(f"{ctrl_dev}: channel open failed with ENODEV", file=sys.stderr)
            else:
                print(f"{ctrl_dev}: {exc}", file=sys.stderr)
        except Exception as exc:
            last_error = exc
            print(f"{ctrl_dev}: {exc}", file=sys.stderr)

    if last_error:
        print(f"failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
