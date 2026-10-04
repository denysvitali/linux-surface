#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test bounded log retention with fake proc reads and kernel messages."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('early-log.sh')


class EarlyLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin',
                        SPX_DIAG_ROOT=str(self.root / 'evidence'),
                        TEST_CMDLINE='spx_diag=20260913 spx_attempt=test')
        self.command('cat', '''case "$1" in
/proc/cmdline) printf '%s\\n' "$TEST_CMDLINE";;
/proc/sys/kernel/random/boot_id) echo test-boot;;
/proc/uptime) echo '20.00 40.00';;
*) exec /bin/cat "$@";;
esac
''')
        self.command('dmesg', 'echo "retained kernel message"\n')
        self.command('sync', 'exit 0\n')
        self.command('sleep', 'exit 0\n')

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\nset -eu\n' + body)
        path.chmod(0o755)

    def run_logger(self):
        return subprocess.run(['sh', str(SCRIPT)], env=self.env,
                              capture_output=True, text=True)

    def test_normal_boot_does_not_collect(self):
        for cmdline in ['spx_boot=known-good', 'spx_diag=20260913-extra',
                        'unrelated=spx_diag=20260913']:
            with self.subTest(cmdline=cmdline):
                self.env['TEST_CMDLINE'] = cmdline
                result = self.run_logger()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.root / 'evidence').exists())

    def test_bounded_snapshots_survive_service_restart(self):
        for _ in range(2):
            result = self.run_logger()
            self.assertEqual(result.returncode, 0, result.stderr)
        runs = list((self.root / 'evidence/boots/test-boot').glob('early.*'))
        self.assertEqual(len(runs), 2)
        for run in runs:
            self.assertEqual(len(list(run.glob('*.kernel.log'))), 90)
            self.assertEqual(len(list(run.glob('*.uptime'))), 90)
            self.assertFalse(list(run.glob('*.tmp')))
            self.assertEqual((run / '90.kernel.log').read_text(),
                             'retained kernel message\n')
            self.assertEqual(run.stat().st_mode & 0o777, 0o700)

    def test_capture_failure_preserves_completed_snapshot(self):
        self.command('dmesg', '''if [ -e "$SPX_DIAG_ROOT/captured" ]; then
    echo 'incomplete snapshot'
    exit 1
fi
touch "$SPX_DIAG_ROOT/captured"
echo 'complete snapshot'
''')
        result = self.run_logger()
        self.assertNotEqual(result.returncode, 0)
        run, = (self.root / 'evidence/boots/test-boot').glob('early.*')
        self.assertEqual((run / '1.kernel.log').read_text(),
                         'complete snapshot\n')
        self.assertFalse((run / '2.kernel.log').exists())
        self.assertTrue((run / '2.kernel.tmp').exists())


if __name__ == '__main__':
    unittest.main()
