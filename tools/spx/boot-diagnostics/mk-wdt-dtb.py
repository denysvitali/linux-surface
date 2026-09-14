#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Add the APSS watchdog node to an existing DTB, changing nothing else.

Stage 1 of the recovery validation needs a DTB that differs from the deployed
known-good image by exactly one node. Rebuilding from the 6.18 worktree does
not give that: the tree has moved on since sc8180x-surface-pro-x.dtb.wsa was
deployed, and a fresh build differs by well over a thousand lines. So this
patches the deployed binary instead, and then proves the result by decompiling
both and diffing the text.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

NODE = re.compile(r'^\t\tmailbox@17c00000 \{$')
END = '\t\t};'
SLEEP_CLK = re.compile(r'^\t\tsleep-clk \{(.*?)^\t\t\};', re.S | re.M)
PHANDLE = re.compile(r'phandle = <(0x[0-9a-f]+)>;')


def decompile(dtb, out):
    subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', '-o', str(out), str(dtb)],
                   check=True)


def sleep_clk_phandle(dts):
    match = SLEEP_CLK.search(dts)
    if not match:
        sys.exit('no sleep-clk node in the base DTB')
    handle = PHANDLE.search(match.group(1))
    if not handle:
        sys.exit('sleep-clk has no phandle; the DTB was not built with -@')
    return handle.group(1)


def insert(dts, phandle):
    if re.search(r"watchdog@17c10000\s*\{", dts):
        sys.exit("watchdog node already exists in the base DTB")
    lines = dts.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if NODE.match(line):
            break
    else:
        sys.exit('no mailbox@17c00000 anchor in the base DTB')
    for end in range(index, len(lines)):
        if lines[end].rstrip('\n') == END:
            break
    else:
        sys.exit('unterminated mailbox@17c00000 node')
    node = [
        '\n',
        '\t\twatchdog@17c10000 {\n',
        '\t\t\tcompatible = "qcom,apss-wdt-sm8150", "qcom,kpss-wdt";\n',
        '\t\t\treg = <0x00 0x17c10000 0x00 0x1000>;\n',
        f'\t\t\tclocks = <{phandle}>;\n',
        '\t\t\tinterrupts = <0x00 0x00 0x01>;\n',
        '\t\t};\n',
    ]
    return ''.join(lines[:end + 1] + node + lines[end + 1:])


def validate_result(expected, actual):
    # Compare the entire canonical decompilation, not just added-line counts.
    if actual != expected:
        sys.exit('refusing to publish: result differs from the exact added node')


def publish(candidate, output):
    # Stage on the destination filesystem, then link without replacing anything.
    # A concurrent creator or a symlink at output causes link() to fail closed.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(candidate.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()

    if a.out.exists() or a.out.is_symlink():
        sys.exit('refusing to overwrite an existing output')

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        decompile(a.base, tmp / 'base.dts')
        base_dts = (tmp / 'base.dts').read_text()
        expected = insert(base_dts, sleep_clk_phandle(base_dts))
        (tmp / 'patched.dts').write_text(expected)
        candidate = tmp / 'candidate.dtb'
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(candidate),
                        str(tmp / 'patched.dts')], check=True)
        decompile(candidate, tmp / 'result.dts')
        validate_result(expected, (tmp / 'result.dts').read_text())
        publish(candidate, a.out)

    print(f'added exactly one watchdog node to {a.out}')


if __name__ == '__main__':
    main()
