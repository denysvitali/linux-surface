#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Check the watchdog snippets against the driver's arithmetic and GRUB syntax."""
from pathlib import Path
import subprocess
import tempfile
import unittest

import wdt

GRUB_CHECK = 'grub-script-check'


class ArithmeticTests(unittest.TestCase):
    def test_kpss_offsets_match_the_driver_layout(self):
        # drivers/watchdog/qcom-wdt.c: reg_offset_data_kpss
        self.assertEqual(wdt.WDT_BASE + 0x4, wdt.WDT_RST)
        self.assertEqual(wdt.WDT_BASE + 0x8, wdt.WDT_EN)
        self.assertEqual(wdt.WDT_BASE + 0xC, wdt.WDT_STS)
        self.assertEqual(wdt.WDT_BASE + 0x10, wdt.WDT_BARK)
        self.assertEqual(wdt.WDT_BASE + 0x14, wdt.WDT_BITE)

    def test_default_timeout_matches_qcom_wdt_start(self):
        lines = wdt.arm_lines(30, 1)
        # bark = (timeout - pretimeout) * rate, bite = timeout * rate
        self.assertIn('write_dword 0x17c10010 0xe7f8c', lines)
        self.assertIn('write_dword 0x17c10014 0xeff88', lines)

    def test_bite_field_must_fit_twenty_bits(self):
        self.assertEqual(wdt.MAX_TIMEOUT_S, wdt.MAX_TICK_COUNT // wdt.RATE_HZ)
        self.assertEqual(wdt.MAX_TIMEOUT_S, 32)
        with self.assertRaises(ValueError):
            wdt.arm_lines(wdt.MAX_TIMEOUT_S + 1)
        with self.assertRaises(ValueError):
            wdt.arm_lines(0)

    def test_pretimeout_must_precede_the_bite(self):
        with self.assertRaises(ValueError):
            wdt.arm_lines(30, 30)


class SnippetTests(unittest.TestCase):
    def check(self, mode, timeout=30, pretimeout=1):
        snippet = wdt.render(mode, timeout, pretimeout)
        result = subprocess.run([GRUB_CHECK, '/dev/stdin'], input=snippet,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return snippet.splitlines()

    def test_all_modes_are_valid_grub(self):
        for mode in ('probe', 'arm', 'disarm'):
            with self.subTest(mode=mode):
                self.check(mode)

    def test_arm_starts_by_disabling_then_ending_enabled(self):
        lines = [line.strip() for line in self.check('arm')]
        writes = [line for line in lines if line.startswith('write_dword')]
        self.assertEqual(writes[0], 'write_dword 0x17c10008 0x0')
        self.assertEqual(writes[-1], 'write_dword 0x17c10008 0x1')

    def test_probe_only_reads(self):
        lines = [line.strip() for line in self.check('probe')]
        self.assertFalse([line for line in lines if line.startswith('write_')])
        reads = [line for line in lines if line.startswith('read_dword')]
        self.assertEqual(reads, [
            'read_dword 0x17c10008',
            'read_dword 0x17c1000c',
        ])
        self.assertTrue(all(len(line.split()) == 2 for line in reads))

    def test_disarm_only_clears_the_enable_bit(self):
        lines = [line.strip() for line in self.check('disarm')]
        self.assertEqual([line for line in lines if line.startswith('write_')],
                         ['write_dword 0x17c10008 0x0'])


class CliTests(unittest.TestCase):
    def test_out_file_matches_stdout(self):
        script = Path(wdt.__file__)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'snippet.cfg'
            stdout = subprocess.run(
                [str(script), '--mode', 'arm', '--timeout', '30', '--out', str(out)],
                text=True, capture_output=True, check=True).stdout
            self.assertEqual(out.read_text(), stdout)

    def test_out_of_range_timeout_is_refused(self):
        script = Path(wdt.__file__)
        result = subprocess.run([str(script), '--mode', 'arm', '--timeout', '60'],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
