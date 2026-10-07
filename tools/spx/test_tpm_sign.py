#!/usr/bin/env python3
"""Offline admission, independent verification and failed-run cleanup checks."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spx_tpm_sign', Path(__file__).with_name('tpm') / 'sign.py')
sign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign)


def snapshot():
    return dict(inventory=dict(transient=[], persistent=[0x81000001], nv=[0x01000001]),
                algorithms=[0xb, 0x23, 0x18], commands=sorted(sign.COMMANDS), curves=[3],
                public=dict(complete=True, manufacturer='QCOM', pcr0_algorithm=0xb,
                            pcr0='ab' * 32, pcr_update=91))


class Fake(sign.Live):
    def __init__(self, output):
        super().__init__(output, '20261007test', 'test-kernel')
        self.before, self.after = snapshot(), snapshot()
        self.tampered_code = 1
        self.after_failure = False
        self.key_text = 'Key is valid\nASN1 OID: prime256v1\nNIST CURVE: P-256\n'
        self.effect_seen = False

    def gate(self):
        return 'test-boot'

    def command(self, label, argv, **kwargs):
        self.commands.append(dict(label=label, argv=list(map(str, argv))))
        text, code = '', 0
        if label == 'version':
            text = 'tool="tpm2_getcap" version="5.8"\n'
        elif label == 'createprimary':
            self.effect_seen = True
            (self.work / 'key.ctx').write_bytes(b'ENCRYPTED PRIVATE CONTEXT')
            (self.work / 'public.pem').write_text('public-key')
        elif label == 'public-key':
            text = self.key_text
        elif label == 'digest':
            (self.work / 'digest.bin').write_bytes(sign.hashlib.sha256((self.work / 'message.bin').read_bytes()).digest())
        elif label == 'sign':
            (self.work / 'signature.der').write_bytes(b'public-signature')
        elif label == 'verify-original':
            text = 'Verified OK\n'
        elif label == 'verify-tampered':
            code, text = self.tampered_code, 'Verification failure\n'
        (self.output / (label + '.log')).write_text(text)
        return code, text

    def snapshot(self, label):
        self.commands.append(dict(label=label))
        if label == 'after' and self.after_failure:
            raise subprocess.TimeoutExpired(['snapshot-child'], 15)
        return copy.deepcopy(self.before if label == 'before' else self.after)


class SigningTests(unittest.TestCase):
    def run_fake(self, live):
        with patch.object(sign, 'fd_owners', return_value=[]):
            return sign.exercise(live)

    def test_nonroot_gate_stops_before_device_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            live = sign.Live(Path(directory) / 'run', '20261007test', 'test-kernel')
            with patch.object(sign.os, 'geteuid', return_value=1000), patch.object(sign.subprocess, 'Popen') as child:
                result = sign.exercise(live)
            self.assertFalse(result['complete'])
            self.assertFalse(live.output.exists())
            child.assert_not_called()

    def test_wrong_capabilities_never_create_context_and_preserve_public_logs(self):
        for missing in ('manufacturer', 'algorithm', 'curve', 'command'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                live = Fake(Path(directory) / 'run')
                if missing == 'manufacturer': live.before['public']['manufacturer'] = 'OTHER'
                if missing == 'algorithm': live.before['algorithms'].remove(0x18)
                if missing == 'curve': live.before['curves'] = []
                if missing == 'command': live.before['commands'].remove(0x15d)
                live.after = copy.deepcopy(live.before)
                result = self.run_fake(live)
                self.assertFalse(result['complete'])
                self.assertFalse(live.effect_seen)
                self.assertTrue(result['private_files_removed'])
                self.assertTrue((live.output / 'getcap-commands.log').exists())
                self.assertFalse((live.output / 'message.bin').exists())

    def test_success_requires_independent_positive_and_explicit_tampered_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Fake(Path(directory) / 'run')
            result = self.run_fake(live)
            self.assertTrue(result['complete'])
            self.assertFalse(result['secure_boot_acceptance'])
            self.assertTrue(result['inventory_and_pcr_unchanged'])
            self.assertTrue((live.output / 'message.bin').is_file())
            self.assertFalse(live.work.exists())
            create = next(c['argv'] for c in live.commands if c['label'] == 'createprimary')
            self.assertIn('n', create)
            self.assertIn('-R', create)
            self.assertEqual(create[1:3], ['-T', 'device:/dev/tpmrm0'])
            self.assertIn(sign.ATTRIBUTES, create)
            for command in live.commands:
                if 'argv' in command:
                    self.assertNotIn('flushcontext', ' '.join(command['argv']))

    def test_verify_rejects_misleading_exit_and_text(self):
        for code, text, tampered in [(1, 'Verified OK', False), (0, 'noise', False),
                (0, 'Verification failure', True), (2, 'Verification failure', True), (1, 'library error', True)]:
            with self.subTest(code=code, text=text, tampered=tampered), self.assertRaises(AssertionError):
                sign.verify_result(code, text, tampered=tampered)
        sign.verify_result(0, 'Verified OK\n')
        sign.verify_result(1, 'Verification failure\n', tampered=True)

    def test_wrong_key_or_false_tampered_pass_removes_context_and_public_artifacts(self):
        for kind in ('key', 'tampered'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                live = Fake(Path(directory) / 'run')
                if kind == 'key': live.key_text = 'Key is valid\nNIST CURVE: P-384\n'
                else: live.tampered_code = 0
                result = self.run_fake(live)
                self.assertFalse(result['complete'])
                self.assertTrue(result['private_files_removed'])
                self.assertFalse(live.work.exists())
                self.assertFalse((live.output / 'public.pem').exists())

    def test_changed_handles_pcr_or_cleanup_timeout_fails_without_global_flush(self):
        for kind in ('handles', 'pcr', 'update', 'timeout'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                live = Fake(Path(directory) / 'run')
                if kind == 'handles': live.after['inventory']['transient'] = [0x80000001]
                if kind == 'pcr': live.after['public']['pcr0'] = '00' * 32
                if kind == 'update': live.after['public']['pcr_update'] += 1
                if kind == 'timeout': live.after_failure = True
                result = self.run_fake(live)
                self.assertFalse(result['complete'])
                self.assertIn('cleanup_error', result)
                self.assertFalse(live.work.exists())
                self.assertTrue((live.output / 'verify-original.log').exists())
                self.assertFalse((live.output / 'public.pem').exists())

    def test_already_consumed_run_does_not_overwrite_result(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Fake(Path(directory) / 'run')
            self.assertTrue(self.run_fake(live)['complete'])
            original = (live.output / 'result.json').read_bytes()
            live = Fake(live.output)
            self.assertFalse(self.run_fake(live)['complete'])
            self.assertFalse(live.effect_seen)
            self.assertEqual((live.output / 'result.json').read_bytes(), original)

    def test_environment_cannot_redirect_tpm_or_openssl(self):
        with patch.dict(os.environ, {'TPM2TOOLS_TCTI': 'mssim:host=remote', 'TSS2_LOG': 'all+TRACE',
                                     'TPM2TSSENGINE_TCTI': 'swtpm', 'OPENSSL_CONF': 'malicious'}):
            env = sign.clean_environment(Path('/private'))
        self.assertFalse(any(k.startswith(('TPM2', 'TSS2')) for k in env))
        self.assertEqual(env['OPENSSL_CONF'], '/dev/null')
        self.assertEqual(env['HOME'], '/private')

    def test_real_child_timeout_is_bounded_killed_and_reaped_with_log(self):
        with tempfile.TemporaryDirectory() as directory:
            live = sign.Live(Path(directory), '20261007test', 'test-kernel')
            live.work = Path(directory)
            live.deadline = time.monotonic() + 0.4
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                live.command('timeout', [sys.executable, '-c', 'import os,time; print(os.getpid(),flush=True); time.sleep(100)'])
            self.assertLess(time.monotonic() - started, 3)
            pid = int((live.output / 'timeout.log').read_text().strip())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


if __name__ == '__main__':
    unittest.main()
