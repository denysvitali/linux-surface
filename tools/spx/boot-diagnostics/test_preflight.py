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
ORIGIN = '20260922e'
RESULT_PATH = BASE + '/attempts/' + ORIGIN + '/live-baseline-result/result.json'
RELEASE = '7.3.0-rc2-spx-mainline-20260922e+'

def retained_boot(*, result_edits=None, proof_edits=None, payload=None):
    result = {'attempt': ORIGIN, 'boot_id': 'boot-a', 'release': RELEASE,
              'uptime_seconds': 827.19,
              'result': 'passed extended graphical baseline; intentionally retained live mainline session',
              'recovery_return_performed': False}
    result.update(result_edits or {})
    if payload is None:
        payload = json.dumps(result).encode()
    proof = {'attempt': ORIGIN, 'boot_id': 'boot-a', 'release': RELEASE,
             'result_path': RESULT_PATH, 'result_sha256': hashlib.sha256(payload).hexdigest()}
    proof.update(proof_edits or {})
    return {'manifest_edits': {'validated_preboot': proof},
            'edits': {'/proc/cmdline': 'spx_boot=mainline-trial spx_diag=20260913 spx_attempt=' + ORIGIN,
                      '/proc/uptime': '900.0 0.0'},
            'byte_files': {RESULT_PATH: payload}}

class GuardTests(unittest.TestCase):
    def exercise(self, *, edits=None, commands=None, reboot=False, changed_on_recheck=False,
                 already_requested=False, artifact=b'image', manifest_edits=None,
                 byte_files=None, changed_result_on_recheck=False):
        manifest = {'attempt': 'test', 'preboot_id': 'boot-a', 'entry': 'test-entry',
                    'sha256': {'/boot/test-image': hashlib.sha256(b'image').hexdigest()}}
        manifest.update(manifest_edits or {})
        files = {BASE + '/attempt.json': json.dumps(manifest),
                 '/proc/sys/kernel/random/boot_id': 'boot-a',
                 '/proc/cmdline': 'spx_boot=known-good', '/proc/uptime': '180.0 0.0',
                 '/boot/grub/grub.cfg': RECOVERY, '/boot/grub/custom.cfg': ENTRY,
                 RUN + '/entry.cfg': ENTRY}
        files.update(edits or {})
        calls, reads, result_reads = [], 0, 0
        next_entry = ''
        def read_text(path, *args, **kwargs):
            nonlocal reads
            if str(path) == '/proc/sys/kernel/random/boot_id':
                reads += 1
                if changed_on_recheck and reads > 1:
                    return 'boot-b'
            return files[str(path)]
        def read_bytes(path):
            nonlocal result_reads
            if str(path) == '/boot/test-image':
                return artifact
            if byte_files and str(path) in byte_files:
                result_reads += 1
                if changed_result_on_recheck and result_reads > 1:
                    return b'changed result'
                return byte_files[str(path)]
            raise FileNotFoundError(str(path))
        def output(argv, **kwargs):
            key = tuple(argv)
            if commands and key in commands:
                return commands[key]
            if argv[0] == 'uptime': return '2026-09-13 23:00:00'
            if argv == ('uname', '-r'): return RELEASE
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
             patch.object(Path, 'read_bytes', read_bytes), \
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
        message, calls = self.exercise(**kwargs)
        self.assertIsNotNone(message)
        self.assertFalse(any(c[0] == 'grub-editenv' for c in calls))
        self.assertNotIn(['systemctl', '--no-block', 'reboot'], calls)

    def test_dry_run_never_queues_or_reboots(self):
        message, calls = self.exercise()
        self.assertIsNone(message)
        self.assertTrue(all(c[0] == 'grub-script-check' for c in calls))

    def test_reboot_is_blocked_even_with_valid_artifacts(self):
        message, calls = self.exercise(reboot=True)
        self.assertIn('no validated pre-kernel recovery', message)
        self.assertEqual(calls, [])

    def test_reboot_is_blocked_before_reading_a_manifest(self):
        message, calls = self.exercise(reboot=True, edits={BASE + '/attempt.json': 'invalid json'})
        self.assertIn('no validated pre-kernel recovery', message)
        self.assertEqual(calls, [])

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

    def test_pinned_retained_mainline_baseline_is_accepted_read_only(self):
        message, calls = self.exercise(**retained_boot())
        self.assertIsNone(message)
        self.assertTrue(all(c[0] == 'grub-script-check' for c in calls))

    def test_mainline_still_requires_explicit_pinned_proof(self):
        options = retained_boot()
        options.pop('manifest_edits')
        self.assert_blocked(**options)

    def test_validated_mainline_never_enables_reboot(self):
        message, calls = self.exercise(**retained_boot(), reboot=True)
        self.assertIn('no validated pre-kernel recovery', message)
        self.assertEqual(calls, [])

    def test_validated_mainline_preserves_pending_boot_guard(self):
        self.assert_blocked(**retained_boot(), commands={
            ('grub-editenv', '/boot/grub/grubenv', 'list'): 'next_entry=other'})

    def test_validated_mainline_rechecks_boot_and_evidence(self):
        self.assert_blocked(**retained_boot(), changed_on_recheck=True)
        self.assert_blocked(**retained_boot(), changed_result_on_recheck=True)

    def test_validated_mainline_matches_current_boot_and_release(self):
        for field, value in [('boot_id', 'another-boot'), ('release', RELEASE + '-other')]:
            with self.subTest(field=field):
                self.assert_blocked(**retained_boot(proof_edits={field: value}))

    def test_validated_mainline_requires_exact_unique_markers(self):
        valid = 'spx_boot=mainline-trial spx_attempt=' + ORIGIN
        for cmdline in ['spx_boot=known-good spx_attempt=' + ORIGIN,
                        valid.replace('mainline-trial', 'mainline-trial-extra'),
                        'spx_boot=mainline-trial',
                        valid.replace(ORIGIN, ORIGIN + '-other'),
                        valid + ' spx_boot=known-good',
                        valid + ' spx_boot=mainline-trial',
                        valid + ' spx_attempt=' + ORIGIN]:
            with self.subTest(cmdline=cmdline):
                options = retained_boot()
                options['edits']['/proc/cmdline'] = cmdline
                self.assert_blocked(**options)

    def test_proof_requires_complete_string_schema(self):
        for proof in [None, True, {}, [], {'allow': True}]:
            with self.subTest(proof=proof):
                options = retained_boot()
                options['manifest_edits']['validated_preboot'] = proof
                self.assert_blocked(**options)
        for field in retained_boot()['manifest_edits']['validated_preboot']:
            for value in [None, '', 1]:
                with self.subTest(field=field, value=value):
                    self.assert_blocked(**retained_boot(proof_edits={field: value}))

    def test_proof_path_is_pinned_to_a_distinct_archived_attempt(self):
        for attempt_id in ['..', '../20260922e', '/20260922e', 'test']:
            with self.subTest(attempt=attempt_id):
                self.assert_blocked(**retained_boot(proof_edits={'attempt': attempt_id}))
        for path in ['/tmp/result.json', RESULT_PATH + '.backup',
                     RESULT_PATH.replace(ORIGIN, '20260922d')]:
            with self.subTest(path=path):
                self.assert_blocked(**retained_boot(proof_edits={'result_path': path}))

    def test_proof_result_requires_matching_hash_and_readable_json(self):
        for digest in ['0' * 64, 'not-a-hash']:
            with self.subTest(digest=digest):
                self.assert_blocked(**retained_boot(proof_edits={'result_sha256': digest}))
        for payload in [b'{', b'[]', b'null', b'\xff']:
            with self.subTest(payload=payload):
                self.assert_blocked(**retained_boot(payload=payload))
        options = retained_boot()
        options['byte_files'] = {}
        self.assert_blocked(**options)

    def test_result_identity_and_outcome_cannot_be_substituted(self):
        for field, value in [('boot_id', 'another-boot'), ('release', RELEASE + '-other'),
                             ('attempt', '20260922d'), ('result', 'passed'),
                             ('result', 'failed extended graphical baseline'),
                             ('recovery_return_performed', True),
                             ('recovery_return_performed', 0),
                             ('recovery_return_performed', None)]:
            with self.subTest(field=field, value=value):
                self.assert_blocked(**retained_boot(result_edits={field: value}))

    def test_baseline_duration_must_be_finite_sufficient_and_not_in_future(self):
        for age in [None, True, '827.19', 599.99, 900.01,
                    float('nan'), float('inf'), 10 ** 400]:
            with self.subTest(age=age):
                self.assert_blocked(**retained_boot(result_edits={'uptime_seconds': age}))
        message, _ = self.exercise(**retained_boot(result_edits={'uptime_seconds': 600}))
        self.assertIsNone(message)

if __name__ == '__main__':
    unittest.main()
