#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fixture-only tests: no live device, systemctl, validator or trial workload."""
import configparser
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('automatic_validation', HERE / 'automatic-validation.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class AutomaticBootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'evidence'
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.binary = self.root / 'validator'
        self.binary.write_text('fixture executable')
        self.binary.chmod(0o755)
        self.out = self.base / 'boots' / 'fixture-boot' / 'hw-validation'

    def run_hook(self, execute=None, runner=None, repo=None):
        if execute is None:
            def execute(*args, **kwargs):
                self.fail('missing prerequisite must not invoke validator')
        return hook.run_once(self.base, runner or self.binary,
                             self.repo if repo is None else repo,
                             'fixture-boot', 'fixture-kernel', execute)

    def status(self):
        data = json.loads((self.out / 'runner.json').read_text())
        self.assertEqual(data['boot_id'], 'fixture-boot')
        self.assertEqual(data['kernel'], 'fixture-kernel')
        self.assertIn(data['status'], (self.out / 'runner.md').read_text())
        return data

    def test_missing_and_permission_are_explicit(self):
        self.assertEqual(self.run_hook(runner=self.root / 'missing'), 1)
        self.assertEqual(self.status()['status'], 'missing')
        self.binary.chmod(0o644)
        self.assertEqual(self.run_hook(), 1)
        self.assertEqual(self.status()['status'], 'blocked')

    def test_unavailable_repo_is_blocked(self):
        self.assertEqual(self.run_hook(repo=self.root / 'unavailable'), 1)
        self.assertEqual(self.status()['status'], 'blocked')

    def test_busy_is_deferred_and_retry_replaces_status(self):
        self.out.mkdir(parents=True)
        (self.out / 'report.json').write_text('{"retained": true}')
        (self.out / 'report.md').write_text('# Retained completed run')
        def busy(args, **kwargs):
            return subprocess.CompletedProcess(args, 75)
        self.assertEqual(self.run_hook(busy), 75)
        self.assertEqual(self.status()['status'], 'deferred')
        self.assertIn('60 seconds', self.status()['detail'])
        self.assertEqual((self.out / 'report.json').read_text(), '{"retained": true}')
        def completed(args, **kwargs):
            if '--checklist' in args:
                self.assertEqual(args, [str(self.binary), '--checklist', '--output', str(self.out / 'report'),
                                        '--repo', str(self.repo), '--require-current-boot'])
                return subprocess.CompletedProcess(args, 0)
            self.assertIn('--checklist-path', args)
            self.assertNotIn('--capture', args)
            self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
            (self.out / 'report.json').write_text('{"results": []}')
            (self.out / 'report.md').write_text('# Fixture check results')
            return subprocess.CompletedProcess(args, 0)
        self.assertEqual(self.run_hook(completed), 0)
        self.assertEqual(self.status()['status'], 'succeeded')

    def test_interrupted_wrapper_is_failed_but_deferred_is_preserved(self):
        self.out.mkdir(parents=True)
        hook.runner_status(self.out, 'fixture-boot', 'fixture-kernel', 'running', 'Fixture started')
        hook.finalize(self.base, 'fixture-boot', 'fixture-kernel', 'signal')
        self.assertEqual(self.status()['status'], 'failed')
        self.assertIn('signal', self.status()['detail'])
        hook.runner_status(self.out, 'fixture-boot', 'fixture-kernel', 'deferred', 'Fixture busy', 75)
        hook.finalize(self.base, 'fixture-boot', 'fixture-kernel', 'exit-code')
        self.assertEqual(self.status()['status'], 'deferred')

    def test_only_explicit_media_fixture_is_forwarded(self):
        media = self.root / 'verified-fixture.h264'
        def completed(args, **kwargs):
            if '--checklist' in args:
                return subprocess.CompletedProcess(args, 0)
            self.assertEqual(args[args.index('--media') + 1], str(media))
            self.assertEqual(args[-2:], ['--storage-dir', str(self.base)])
            self.assertNotIn('--capture', args)
            (self.out / 'report.json').write_text('{"results": []}')
            (self.out / 'report.md').write_text('# Fixture check results')
            return subprocess.CompletedProcess(args, 0)
        code = hook.run_once(self.base, self.binary, self.repo, 'fixture-boot',
                             'fixture-kernel', completed, media=media)
        self.assertEqual(code, 0)

    def test_explicit_user_forwarded_without_demoting_root_probes(self):
        def completed(args, **kwargs):
            if '--checklist' in args:
                return subprocess.CompletedProcess(args, 0)
            self.assertEqual(args[0], str(self.binary))
            self.assertEqual(args[-2:], ['--user', 'fixtureuser'])
            self.assertNotIn('runuser', args)
            (self.out / 'report.json').write_text('{"results": []}')
            (self.out / 'report.md').write_text('# Fixture check results')
            return subprocess.CompletedProcess(args, 0)
        code = hook.run_once(self.base, self.binary, self.repo, 'fixture-boot',
                             'fixture-kernel', completed, user='fixtureuser')
        self.assertEqual(code, 0)

    def test_validator_failure_or_missing_reports_not_success(self):
        self.out.mkdir(parents=True)
        (self.out / 'report.json').write_text('{"old": true}')
        (self.out / 'report.md').write_text('# Old run')
        def failed(args, **kwargs):
            return subprocess.CompletedProcess(args, 2)
        self.assertEqual(self.run_hook(failed), 1)
        self.assertEqual((self.out / 'report.json').read_text(), '{"old": true}')
        self.assertEqual(self.status()['status'], 'failed')
        self.assertEqual(self.status()['exit_code'], 2)
        def check_failed(args, **kwargs):
            if '--checklist' in args:
                return subprocess.CompletedProcess(args, 0)
            (self.out / 'report.json').write_text('{"counts": {"failed": 1, "errors": 0}}')
            (self.out / 'report.md').write_text('# One failed check')
            return subprocess.CompletedProcess(args, 1)
        self.assertEqual(self.run_hook(check_failed), 1)
        self.assertIn('1 failed and 0 error', self.status()['detail'])
        def empty(args, **kwargs):
            return subprocess.CompletedProcess(args, 0)
        self.assertEqual(self.run_hook(empty), 1)
        self.assertEqual(self.status()['status'], 'failed')

    def test_active_checklist_update_failure_is_explicit(self):
        calls = []
        def completed(args, **kwargs):
            calls.append(args)
            if '--checklist' in args:
                return subprocess.CompletedProcess(args, 2)
            (self.out / 'report.json').write_text('{"results": []}')
            (self.out / 'report.md').write_text('# Completed fixture check report')
            return subprocess.CompletedProcess(args, 0)
        self.assertEqual(self.run_hook(completed), 1)
        self.assertEqual(len(calls), 2)
        self.assertIn('active repository checklist update failed', self.status()['detail'])
        self.assertTrue((self.out / 'report.json').is_file())

    def test_execute_permission_or_loader_failure(self):
        for exc, expected in [(PermissionError(), 'blocked'), (FileNotFoundError(), 'missing')]:
            def denied(*args, **kwargs):
                raise exc
            self.assertEqual(self.run_hook(denied), 1)
            self.assertEqual(self.status()['status'], expected)

    def test_verify_requires_saved_current_boot_evidence_without_live_checks(self):
        def forbidden(*args, **kwargs):
            self.fail('missing report must not execute anything')
        self.assertEqual(hook.verify(self.base, self.binary, self.repo, 'fixture-boot', forbidden), 1)
        self.out.mkdir(parents=True)
        (self.out / 'report.json').write_text('{"fixture": true}')
        def reject(args, **kwargs):
            self.assertIn('--require-current-boot', args)
            self.assertIn('--from-report', args)
            self.assertNotIn('--capture', args)
            self.assertNotIn('--output', args)
            return subprocess.CompletedProcess(args, 2)
        self.assertEqual(hook.verify(self.base, self.binary, self.repo, 'fixture-boot', reject), 1)

    def test_missing_validation_prevents_boot_and_promotion_side_effects(self):
        trial_spec = importlib.util.spec_from_file_location('trial_validation_gate', HERE.parent / 'trial.py')
        trial = importlib.util.module_from_spec(trial_spec)
        trial_spec.loader.exec_module(trial)
        with patch.object(trial, 'require_source_boot'), \
                patch.object(trial.os, 'geteuid', return_value=0), \
                patch.object(trial, 'require_automatic_validation', side_effect=RuntimeError('missing boot report')), \
                patch.object(trial, 'recovery') as recovery:
            for action in (trial.boot, trial.promote):
                with self.assertRaisesRegex(RuntimeError, 'missing boot report'):
                    action(None)
            recovery.assert_not_called()

    def test_staging_installs_one_unit_without_commands(self):
        module = self.repo / 'tools/spx/hw-validation/go.mod'
        module.parent.mkdir(parents=True)
        module.write_text('module fixture\ngo 1.22\n')
        root = self.root / 'stage'
        def forbidden(*args, **kwargs):
            self.fail('staging root must not invoke systemctl or functional commands')
        media = self.root / 'verified-fixture.h264'
        hook.install(self.repo, self.binary, root, forbidden, media=media, user="fixtureuser")
        private = root / 'usr/local/lib/spx-boot-diagnostics'
        self.assertEqual((private / 'spx-hw-validation').read_text(), self.binary.read_text())
        self.assertEqual((private / 'spx-hw-validation').stat().st_mode & 0o777, 0o755)
        self.assertEqual(json.loads((root / 'etc/spx/hw-validation.json').read_text())['repo'], str(self.repo))
        link = root / 'etc/systemd/system/multi-user.target.wants/spx-hw-validation.service'
        self.assertTrue(link.is_symlink())
        self.assertTrue(link.is_file())
        unit = configparser.ConfigParser(interpolation=None)
        unit.read(root / 'etc/systemd/system/spx-hw-validation.service')
        self.assertEqual(unit['Service']['Restart'], 'no')
        self.assertEqual(unit['Service']['RestartForceExitStatus'], '75')
        self.assertEqual(unit['Service']['RestartSec'], '60')
        self.assertEqual(unit['Service']['RuntimeMaxSec'], '10min')
        self.assertEqual(unit['Service']['TimeoutStopSec'], '20s')
        self.assertNotIn('ConditionKernelCommandLine', unit['Unit'])
        self.assertEqual(unit['Unit']['Wants'], 'network-online.target')
        self.assertIn('network-online.target', unit['Unit']['After'])
        hook.install(self.repo, None, root, forbidden)
        self.assertTrue((private / 'spx-hw-validation').is_file())
        config = json.loads((root / 'etc/spx/hw-validation.json').read_text())
        self.assertEqual(config['media'], str(media))
        self.assertEqual(config['storage_dir'], '/var/lib/spx-boot-diagnostics')
        self.assertEqual(config['user'], 'fixtureuser')

    def test_trial_install_and_promotion_only_install_hook(self):
        trial_path = HERE.parent / 'trial.py'
        trial_spec = importlib.util.spec_from_file_location('trial_for_automatic_fixture', trial_path)
        trial = importlib.util.module_from_spec(trial_spec)
        trial_spec.loader.exec_module(trial)
        source = trial_path.read_text()
        self.assertEqual(source.count('    ensure_automatic_validation()\n'), 2)
        commands = []
        def capture(args, **kwargs):
            commands.append(args)
            return subprocess.CompletedProcess(args, 0)
        with patch.object(trial, 'HERE', HERE.parent), patch.object(trial.subprocess, 'run', capture):
            trial.ensure_automatic_validation()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][3:], ['install', '--repo', str(trial.REPO)])
        self.assertNotIn('start', commands[0])
        with patch.object(trial, 'HERE', HERE), patch.object(trial.subprocess, 'run', capture):
            trial.ensure_automatic_validation()
        self.assertEqual(commands[1][2], str(HERE / 'automatic-validation.py'))

    def test_missing_binary_install_preserves_explicit_boot_failure(self):
        module = self.repo / 'tools/spx/hw-validation/go.mod'
        module.parent.mkdir(parents=True)
        module.write_text('module fixture\ngo 1.22\n')
        root = self.root / 'stage'
        hook.install(self.repo, root=root, control=lambda *a, **kw: self.fail('systemctl'))
        binary = root / 'usr/local/lib/spx-boot-diagnostics/spx-hw-validation'
        self.assertFalse(binary.exists())
        self.assertEqual(self.run_hook(runner=binary), 1)
        self.assertEqual(self.status()['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
