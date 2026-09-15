#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Build the fixed 4 KiB ARM64 watchdog-expiry payload.

The five instruction words correspond to kexec-hang.S.  Encoding the tiny
payload directly keeps the recovery proof reproducible on the SPX host, whose
installed cross-GCC currently has no matching assembler binary.
"""
import argparse
from pathlib import Path
import struct

IMAGE_SIZE = 4096
HEADER = struct.pack(
    "<IIQQQQQQII",
    0x14000010,                 # b 0x40
    0xD503201F,                 # nop
    0x80000,                    # text_offset
    IMAGE_SIZE,
    2,                          # little endian, 4 KiB pages
    0, 0, 0,
    0x644D5241,                 # ARM\x64
    0,
)
BODY = struct.pack(
    "<III",
    0xD5034FDF,                 # msr daifset, #0xf
    0xD503205F,                 # wfe
    0x17FFFFFF,                 # b to the wfe instruction
)
PAYLOAD = (HEADER + BODY).ljust(IMAGE_SIZE, b"\0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("xb") as stream:
        stream.write(PAYLOAD)
    print(args.output)


if __name__ == "__main__":
    main()
