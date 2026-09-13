#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exercise reboot guards with all filesystem/process effects mocked."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).with_name('preflight.py').read_text()
BASE = '/var/lib/spx-boot-diagnostics'
RUN = BASE + '/attempts/test'
ENTRY = 'menuentry "test" --id test-entry {\n linux /test-image\n}'
RECOVERY = ('set default="spx-known-good"\n'
            'menuentry "Surface Pro X known-good (.dtb.wsa)" --id spx-known-good {\n'
            ' linux /recovery ramoops.mem_address=0x9a480000 ramoops.mem_size=0x100000 ramoops.record_size=0x40000 ramoops.console_size=0x20000 ramoops.pmsg_size=0 ramoops.ftrace_size=0\n}')

class GuardTests(unittest.TestCase):
    def exercise(self, *, edits=None, commands=None, reboot=False, changed_on_recheck=False, already_requested=False, artifact=b'image'):
        manifest = {'attempt': 'test', 'preboot_id': 'boot-a', 'entry': 'test-entry',
                    'sha256': {'/boot/test-image': hashlib.sha256(b'image').hexdigest()}}
        files = {BASE + '/attempt.json': json.dumps(manifest),
                 '/proc/sys/kernel/random/boot_id': 'boot-a',
                 '/proc/cmdline': 'spx_boot=known-good', '/proc/uptime': '180.0 0.0',
                 '/boot/grub/grub.cfg': RECOVERY, '/boot/grub/custom.cfg': ENTRY,
                 RUN + '/entry.cfg': ENTRY}
        files.update(edits or {})
        calls, reads = [], 0
        next_entry = ''
        def read_text(path, *args, **kwargs):
            nonlocal reads
            if str(path) == '/proc/sys/kernel/random/boot_id':
                reads += 1
                if changed_on_recheck and reads > 1:
                    return 'boot-b'
            return files[str(path)]
        def output(argv, **kwargs):
            key = tuple(argv)
            if commands and key in commands:
                return commands[key]
            if argv[0] == 'uptime': return '2026-09-13 23:00:00'
            if argv[0] == 'grub-editenv': return 'saved_entry=spx-known-good\nnext_entry=' + next_entry
            if argv[0] == 'efibootmgr': return 'BootCurrent: 0005'
            if argv[:2] == ('systemctl', 'is-enabled'): return 'enabled'
            if argv[:2] == ('systemctl', 'show'): return '0'
            raise AssertionError(argv)
        def run(argv, **kwargs):
            nonlocal next_entry
            calls.append(argv)
            if argv[:3] == ['grub-editenv', '/boot/grub/grubenv', 'set']:
                next_entry = argv[3].split('=', 1)[1]
            return subprocess.CompletedProcess(argv, 0)
        marker = MagicMock()
        marker.__enter__.return_value = marker
        exit_message = None
        with patch.object(Path, 'read_text', read_text), \
             patch.object(Path, 'read_bytes', return_value=artifact), \
             patch.object(Path, 'exists', return_value=already_requested), \
             patch.object(Path, 'write_text'), patch.object(Path, 'open', return_value=marker), \
             patch('subprocess.check_output', side_effect=output), \
             patch('subprocess.run', side_effect=run), \
             patch('os.sync'), patch('os.fsync'), \
             patch('sys.stdout', new_callable=io.StringIO), \
             patch('sys.argv', ['preflight.py'] + (['--reboot'] if reboot else [])):
            try:
                exec(compile(SCRIPT, 'preflight.py', 'exec'), {'__name__': '__main__'})
            except SystemExit as exc:
                exit_message = str(exc)
        return exit_message, calls

    def assert_blocked(self, **kwargs):
        message, calls = self.exercise(reboot=True, **kwargs)
        self.assertIsNotNone(message)
        self.assertFalse(any(c[0] == 'grub-editenv' for c in calls))
        self.assertNotIn(['systemctl', '--no-block', 'reboot'], calls)

    def test_dry_run_never_queues_or_reboots(self):
        message, calls = self.exercise()
        self.assertIsNone(message)
        self.assertTrue(all(c[0] == 'grub-script-check' for c in calls))

    def test_one_explicit_reboot_after_checks(self):
        message, calls = self.exercise(reboot=True)
        self.assertIsNone(message)
        self.assertEqual(calls.count(['systemctl', '--no-block', 'reboot']), 1)

    def test_changed_boot_is_not_retried(self):
        self.assert_blocked(edits={'/proc/sys/kernel/random/boot_id': 'boot-b'})

    def test_recent_boot_is_not_rebooted(self):
        self.assert_blocked(edits={'/proc/uptime': '119.9 0'})

    def test_test_boot_is_not_rebooted(self):
        self.assert_blocked(edits={'/proc/cmdline': 'spx_diag=20260913'})

    def test_changed_entry_is_rejected(self):
        self.assert_blocked(edits={'/boot/grub/custom.cfg': ENTRY.replace('/test-image', '/other-image')})

    def test_pending_boot_is_not_overwritten(self):
        self.assert_blocked(commands={('grub-editenv', '/boot/grub/grubenv', 'list'): 'next_entry=other'})

    def test_efi_bootnext_is_rejected(self):
        self.assert_blocked(commands={('efibootmgr',): 'BootNext: 0000'})

    def test_prior_reboot_request_is_not_repeated(self):
        self.assert_blocked(already_requested=True)

    def test_corrupt_image_is_rejected(self):
        self.assert_blocked(artifact=b'corrupt')

    def test_pmsg_layout_prefix_is_not_accepted(self):
        self.assert_blocked(edits={'/boot/grub/grub.cfg': RECOVERY.replace('ramoops.pmsg_size=0', 'ramoops.pmsg_size=0x1000')})

    def test_boot_change_during_preflight_is_rejected(self):
        self.assert_blocked(changed_on_recheck=True)

if __name__ == '__main__':
    unittest.main()
