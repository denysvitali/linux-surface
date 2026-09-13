#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Render a bounded SPX test entry with persistent GRUB loading checkpoints."""
import argparse
import re

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--attempt', required=True)
p.add_argument('--entry', required=True)
p.add_argument('--kernel', required=True)
p.add_argument('--initrd', required=True)
p.add_argument('--dtb', required=True)
p.add_argument('--cmdline', required=True)
a = p.parse_args()
# The inputs become GRUB code. Accept only the literal tokens used by these
# entries, with no shell/GRUB substitutions, quotes, commands or newlines.
for value in [a.attempt, a.entry]:
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', value):
        p.error('invalid attempt or entry identifier')
for value in [a.kernel, a.initrd, a.dtb]:
    if not re.fullmatch(r'/[a-zA-Z0-9_./+-]+', value):
        p.error('invalid boot artifact path')
if not re.fullmatch(r'[a-zA-Z0-9_./,:=+ -]+', a.cmdline):
    p.error('invalid literal kernel command line')

def mark(stage, indent=' '):
    print(indent + 'set spx_diag_stage=' + stage)
    print(indent + 'save_env spx_diag_attempt spx_diag_stage')

loads = [('insmod fdt', 'fdt-module'),
         ('devicetree ' + a.dtb, 'dtb'),
         ('linux ' + a.kernel + ' ' + a.cmdline, 'kernel'),
         ('initrd ' + a.initrd, 'initramfs')]

def load(index=0, indent=' '):
    if index == len(loads):
        mark('handoff-ready', indent)
        return
    command, stage = loads[index]
    print(indent + 'if ' + command + '; then')
    mark(stage, indent + ' ')
    load(index + 1, indent + ' ')
    print(indent + 'else')
    mark(stage + '-failed', indent + ' ')
    print(indent + ' echo "SPX loader failed: ' + stage + '; returning to recovery menu"')
    print(indent + ' sleep --interruptible 10')
    print(indent + ' configfile $prefix/grub.cfg')
    print(indent + 'fi')

print('menuentry "SPX bounded boot diagnostic ' + a.attempt + '" --id ' + a.entry + ' {')
print(' set spx_diag_attempt=' + a.attempt)
mark('entered')
load()
print('}')
