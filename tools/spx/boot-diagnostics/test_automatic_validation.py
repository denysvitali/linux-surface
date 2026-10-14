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
        # Never inspect the host's network when a wrapper test uses defaults.
        original_wait = hook.wait_for_network
        def fixture_wait(seconds=90, clock=hook.time.monotonic,
                         sleep=hook.time.sleep, route_reader=Path.read_text):
            if route_reader is Path.read_text:
                route_reader = lambda path: 'eth0 00000000 00000000 0001 0 0 0 00000000' if str(path) == '/proc/net/route' else ''
            return original_wait(seconds, clock, sleep, route_reader)
        self.addCleanup(patch.stopall)
        patch.object(hook, 'wait_for_network', side_effect=fixture_wait).start()

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

    @staticmethod
    def route_reader_for(values):
        reads = iter(values)
        def reader(path):
            value = next(reads, None)
            return value or ''
        return reader

    def test_network_wait_ready_immediately(self):
        now = [0.0]
        elapsed, ready = hook.wait_for_network(90, lambda: now[0],
            lambda delay: self.fail('ready route must not sleep'),
            self.route_reader_for(['Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\nwlan0 00000000 0100000A 0001 0 0 100 00000000 0 0 0', '']))
        self.assertTrue(ready)
        self.assertEqual(elapsed, 0)

    def test_network_wait_becomes_ready_after_polls(self):
        now = [0.0]
        def sleep(delay):
            now[0] += delay
        route = 'wlan0 00000000 0100000A 0001 0 0 100 00000000 0 0 0'
        elapsed, ready = hook.wait_for_network(90, lambda: now[0], sleep,
            self.route_reader_for(['', '', '', '', route, '']))
        self.assertTrue(ready)
        self.assertEqual(elapsed, 2)

    def test_network_wait_disabled_still_records_current_readiness(self):
        now = [4.0]
        elapsed, ready = hook.wait_for_network(0, lambda: now[0],
            lambda delay: self.fail('disabled wait must not sleep'),
            self.route_reader_for(['', '']))
        self.assertFalse(ready)
        self.assertEqual(elapsed, 0)

    def test_malformed_route_files_are_unready(self):
        elapsed, ready = hook.wait_for_network(0, lambda: 1.0, lambda _: None,
            self.route_reader_for(['bad route\nwlan0 00000000 0 nope 0 0 1 00000000', 'too few fields']))
        self.assertFalse(ready)
        self.assertEqual(elapsed, 0)

    def test_network_wait_deadline_runs_validator_and_is_recorded(self):
        now = [0.0]
        def sleep(delay):
            now[0] += delay
        def execute(args, **kwargs):
            if '--checklist' in args:
                return subprocess.CompletedProcess(args, 0)
            self.assertEqual(now[0], 2)
            (self.out / 'report.json').write_text('{"results": []}')
            (self.out / 'report.md').write_text('# Fixture report')
            return subprocess.CompletedProcess(args, 0)
        code = hook.run_once(self.base, self.binary, self.repo, 'fixture-boot',
            'fixture-kernel', execute, network_wait_seconds=2, clock=lambda: now[0],
            sleep=sleep, route_reader=self.route_reader_for(['', '', '', '', '', '']))
        self.assertEqual(code, 0)
        status = self.status()
        self.assertEqual(status['network_wait_seconds'], 2)
        self.assertFalse(status['network_default_route_at_suite_start'])
        self.assertIn('wait: 2.000s', (self.out / 'runner.md').read_text())

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

    def test_media_directory_default_and_override(self):
        default = self.base / 'fixtures/media'
        for selected, create_default, expected in (
                (None, False, None), (None, True, default),
                (self.root / 'explicit-media', True, self.root / 'explicit-media')):
            with self.subTest(selected=selected, create_default=create_default):
                if create_default:
                    default.mkdir(parents=True, exist_ok=True)
                def completed(args, **kwargs):
                    if '--checklist' in args:
                        return subprocess.CompletedProcess(args, 0)
                    if expected is None:
                        self.assertNotIn('--media-dir', args)
                    else:
                        self.assertEqual(args[args.index('--media-dir') + 1], str(expected))
                    self.assertEqual(args[args.index('--media') + 1], '/fixture.h264')
                    self.assertNotIn('--capture', args)
                    (self.out / 'report.json').write_text('{"results": []}')
                    (self.out / 'report.md').write_text('# Fixture check results')
                    return subprocess.CompletedProcess(args, 0)
                self.assertEqual(hook.run_once(
                    self.base, self.binary, self.repo, 'fixture-boot', 'fixture-kernel',
                    completed, media=Path('/fixture.h264'), media_dir=selected), 0)

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
        hook.install(self.repo, self.binary, root, forbidden, media=media, user="fixtureuser", media_dir=self.root / "media-dir")
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
        self.assertEqual(unit['Service']['RuntimeMaxSec'], '15min')
        self.assertEqual(unit['Service']['TimeoutStopSec'], '20s')
        self.assertNotIn('ConditionKernelCommandLine', unit['Unit'])
        self.assertEqual(unit['Unit']['Wants'], 'network-online.target')
        self.assertIn('network-online.target', unit['Unit']['After'])
        hook.install(self.repo, None, root, forbidden)
        self.assertTrue((private / 'spx-hw-validation').is_file())
        config = json.loads((root / 'etc/spx/hw-validation.json').read_text())
        self.assertEqual(config['network_wait_seconds'], 90)
        self.assertEqual(config['media'], str(media))
        self.assertEqual(config['media_dir'], str(self.root / 'media-dir'))
        self.assertEqual(config['storage_dir'], '/var/lib/spx-boot-diagnostics')
        self.assertEqual(config['user'], 'fixtureuser')

    def test_camera_capture_setting_default_enable_retain_disable(self):
        module = self.repo / 'tools/spx/hw-validation/go.mod'
        module.parent.mkdir(parents=True)
        module.write_text('module fixture\ngo 1.22\n')
        root = self.root / 'stage'
        config = root / 'etc/spx/hw-validation.json'
        def install(*flags):
            self.assertEqual(hook.main(['install', '--repo', str(self.repo),
                                        '--root', str(root), *flags]), 0)
            return json.loads(config.read_text())
        self.assertIs(install()['camera_capture'], False)
        self.assertIs(install('--camera-capture')['camera_capture'], True)
        self.assertIs(install()['camera_capture'], True)
        self.assertIs(install('--no-camera-capture')['camera_capture'], False)
        self.assertIs(install()['camera_capture'], False)
        config.write_text('{"camera_capture": "true"}')
        self.assertIs(install()['camera_capture'], False)
        with self.assertRaises(SystemExit):
            install('--camera-capture', '--no-camera-capture')
        with self.assertRaises(SystemExit):
            install('--capture-microphone')

    def test_camera_capture_forwarded_without_microphone_or_sound(self):
        for enabled in (False, True, 'true', 1):
            with self.subTest(enabled=enabled):
                def completed(args, **kwargs):
                    self.assertNotIn('--capture', args)
                    self.assertNotIn('--capture-microphone', args)
                    if '--checklist' in args:
                        self.assertNotIn('--capture-camera', args)
                    else:
                        self.assertEqual('--capture-camera' in args, enabled is True)
                        running = self.status()['detail']
                        self.assertIn('Camera capture ' + ('enabled' if enabled is True else 'disabled'), running)
                        self.assertIn('microphone capture disabled', running)
                        (self.out / 'report.json').write_text('{"results": []}')
                        (self.out / 'report.md').write_text('# Fixture results')
                    return subprocess.CompletedProcess(args, 0)
                self.assertEqual(hook.run_once(self.base, self.binary, self.repo,
                    'fixture-boot', 'fixture-kernel', completed, camera_capture=enabled), 0)
                self.assertIn('microphone capture disabled', self.status()['detail'])

    def test_run_reads_only_boolean_camera_setting(self):
        config = self.root / 'settings.json'
        for value in (True, False, 'true', 1, None):
            config.write_text(json.dumps(dict(repo=str(self.repo), camera_capture=value,
                                             microphone_capture=True, capture=True)))
            # Fake boot identity as well as the runner; no live boot reads.
            def read(path):
                if path == config:
                    return config.read_bytes().decode()
                return 'fixture-identity'
            with patch.object(Path, 'read_text', read), patch.object(hook, 'run_once', return_value=0) as run:
                self.assertEqual(hook.main(['run', '--config', str(config)]), 0)
                self.assertIs(run.call_args.kwargs['camera_capture'], value is True)
                self.assertNotIn('microphone_capture', run.call_args.kwargs)

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
