#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Render GRUB snippets that arm the Surface Pro X APSS watchdog before handoff.

Experimental boots are blocked until recovery covers a hang before Linux runs.
This renders the pre-kernel half of that recovery: GRUB writes the Qualcomm APSS
watchdog registers through the memrw module, so a hang after handoff is reset by
the hardware rather than requiring a manual power cycle.

Register layout and clock rate come from the mainline qcom-wdt driver and the
SoC device tree, not from a guessed address. See RECOVERY.md for the staged
validation that must pass before the reboot lock can be lifted.
"""
import argparse
from pathlib import Path

# sc8180x.dtsi: watchdog@17c10000, clocks = <&sleep_clk> (32764 Hz).
# qcom-wdt.c reg_offset_data_kpss is used by every "qcom,kpss-wdt" fallback.
WDT_BASE = 0x17C10000
WDT_RST = WDT_BASE + 0x04
WDT_EN = WDT_BASE + 0x08
WDT_STS = WDT_BASE + 0x0C
WDT_BARK = WDT_BASE + 0x10
WDT_BITE = WDT_BASE + 0x14

RATE_HZ = 32764
ENABLE = 1
DISABLE = 0
# The bite time field is 20 bits wide; qcom-wdt refuses a rate above this.
MAX_TICK_COUNT = 0xFFFFF
MAX_TIMEOUT_S = MAX_TICK_COUNT // RATE_HZ


def ticks(seconds):
    return seconds * RATE_HZ


def arm_lines(timeout_s, pretimeout_s=1):
    """Mirror qcom_wdt_start(): disable, reset, load times, enable."""
    if not 0 < timeout_s <= MAX_TIMEOUT_S:
        raise ValueError(f'timeout must be 1..{MAX_TIMEOUT_S}s')
    if not 0 <= pretimeout_s < timeout_s:
        raise ValueError('pretimeout must be smaller than the timeout')
    return [
        'insmod memrw',
        f'write_dword 0x{WDT_EN:08x} 0x{DISABLE:x}',
        f'write_dword 0x{WDT_RST:08x} 0x1',
        f'write_dword 0x{WDT_BARK:08x} 0x{ticks(timeout_s - pretimeout_s):x}',
        f'write_dword 0x{WDT_BITE:08x} 0x{ticks(timeout_s):x}',
        f'write_dword 0x{WDT_EN:08x} 0x{ENABLE:x}',
    ]


def disarm_lines():
    return [
        'insmod memrw',
        f'write_dword 0x{WDT_EN:08x} 0x{DISABLE:x}',
    ]


def probe_lines():
    """Read-only. Print what the bootloader can see at the watchdog registers."""
    return [
        'insmod memrw',
        f'read_dword 0x{WDT_EN:08x}',
        f'read_dword 0x{WDT_STS:08x}',
    ]


def render(mode, timeout_s, pretimeout_s):
    if mode == 'probe':
        body = probe_lines()
    elif mode == 'arm':
        body = arm_lines(timeout_s, pretimeout_s) + [
            'set spx_wdt_armed=' + str(timeout_s),
            'save_env spx_wdt_armed',
        ]
    else:
        body = disarm_lines()
    return '\n'.join(' ' + line for line in body) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['probe', 'arm', 'disarm'], required=True)
    p.add_argument('--timeout', type=int, default=30,
                   help=f'watchdog bite time in seconds (max {MAX_TIMEOUT_S})')
    p.add_argument('--pretimeout', type=int, default=1)
    p.add_argument('--out', type=Path, help='write the snippet here as well')
    a = p.parse_args()
    try:
        snippet = render(a.mode, a.timeout, a.pretimeout)
    except ValueError as exc:
        p.error(str(exc))
    if a.out:
        a.out.write_text(snippet)
    print(snippet, end='')


if __name__ == '__main__':
    main()
