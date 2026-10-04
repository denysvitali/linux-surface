#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Supply this installation's Bluetooth address to a copied SPX boot DTB."""
import argparse
import json
from pathlib import Path
import re

import libfdt


def nodes(tree, parent=0):
    yield parent
    try:
        child = tree.first_subnode(parent)
        while True:
            yield from nodes(tree, child)
            child = tree.next_subnode(child)
    except libfdt.FdtException as error:
        if error.err != -libfdt.NOTFOUND:
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--address', required=True, help='Existing per-installation address, not a shared board default')
    args = p.parse_args()
    assert re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', args.address)
    address = bytes.fromhex(args.address.replace(':', ''))
    assert address not in (b'\0' * 6, b'\xff' * 6) and not address[0] & 1
    assert args.source.resolve() != args.output.resolve() and not args.output.exists()
    tree = libfdt.Fdt(args.source.read_bytes())
    matches = []
    for offset in nodes(tree):
        try:
            compatible = bytes(tree.getprop(offset, 'compatible')).split(b'\0')
        except libfdt.FdtException as error:
            assert error.err == -libfdt.NOTFOUND
            continue
        if b'qcom,wcn3998-bt' in compatible:
            matches.append(tree.get_path(offset))
    assert len(matches) == 1, matches
    path = matches[0]
    tree.resize(tree.totalsize() + 512)
    tree.setprop(tree.path_offset(path), 'local-bd-address', address[::-1])
    tree.pack()
    with args.output.open('xb') as out:
        out.write(bytes(tree.as_bytearray()))
    actual = libfdt.Fdt(args.output.read_bytes())
    assert bytes(actual.getprop(actual.path_offset(path), 'local-bd-address')) == address[::-1]
    print(json.dumps(dict(bluetooth_node=path, address=args.address.upper(), source=str(args.source),
                         output=str(args.output), factory_address_claimed=False)))


if __name__ == '__main__':
    main()
