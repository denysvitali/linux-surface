#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test continuation guards with all network/process operations mocked."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('spx_resume', Path(__file__).with_name('resume.py'))
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)
TRIAL_RELEASE = '7.3.0-rc2-spx-mainline-20260922f+'
TRIAL_ATTEMPT = '20260922f'


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state, self.proc = self.base / 'state', self.base / 'proc'
        self.state.mkdir()
        (self.proc / 'sys/kernel/random').mkdir(parents=True)
        (self.proc / 'sys/kernel/random/boot_id').write_text('recovery-boot\n')
        (self.proc / 'sys/kernel/osrelease').write_text('known-good-kernel\n')
        (self.proc / 'cmdline').write_text('quiet spx_boot=known-good')
        self.marker = self.state / 'resume-armed.json'
        self.record = {'session_id': 'session-a', 'preboot_id': 'preboot',
                       'attempt': 'trial-a', 'directory': str(self.base)}
        self.write_marker()
        (self.state / 'resume-prompt.txt').write_text('Inspect the result and acknowledge this recovery boot.')
        self.daemon_state = self.base / 'daemon.state.json'
        self.daemon_state.write_text(json.dumps({'pid': 999, 'httpPort': 4567}))
        (self.proc / '999').mkdir()
        (self.proc / '999/cmdline').write_bytes(b'/test/happy\0daemon\0start-sync\0')

    def write_marker(self):
        self.marker.write_text(json.dumps(self.record))

    def arm_trial(self):
        self.record.update(attempt=TRIAL_ATTEMPT, expected_trial_attempt=TRIAL_ATTEMPT,
                           expected_trial_release=TRIAL_RELEASE)
        self.write_marker()
        (self.proc / 'cmdline').write_text(f'spx_boot=mainline-trial spx_attempt={TRIAL_ATTEMPT}')
        (self.proc / 'sys/kernel/osrelease').write_text(TRIAL_RELEASE + '\n')

    def claims(self):
        return list((self.state / 'resume-spawn-requests').glob('*.json'))

    def run_helper(self, sessions=None, query_effect=None, output=None,
                   post_effect=None, response=None, raw_response=None, server_effect=None):
        if output is None:
            output = json.dumps(sessions or [])
        if response is None:
            response = {'success': True, 'sessionId': 'session-a'}
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status = 200
        reply.read.return_value = raw_response if raw_response is not None else json.dumps(response).encode()
        with patch.object(subprocess, 'check_output', return_value=output,
                          side_effect=query_effect) as query, \
             patch.object(resume.urllib.request.OpenerDirector, 'open', return_value=reply,
                          side_effect=post_effect) as post, \
             patch.object(resume.socket, 'create_connection', side_effect=server_effect), \
             patch.object(os, 'execve', side_effect=AssertionError('must use daemon, never exec Happy')), \
             contextlib.redirect_stdout(io.StringIO()):
            code = resume.main(self.state, self.proc, Path('/test/happy'), self.daemon_state)
        return code, query, post

    def assert_no_spawn(self, code, query, post, expected=75):
        self.assertEqual(code, expected)
        post.assert_not_called()
        self.assertEqual(self.claims(), [])
        self.assertTrue(self.marker.exists())

    def run_gate(self, replies=None, probe_effect=None):
        elapsed = [0.0]
        def sleep(seconds):
            elapsed[0] += seconds
        if replies is None:
            replies = [0]
        outcomes = iter(replies)
        def probe(*args, **kwargs):
            if probe_effect:
                return probe_effect(elapsed, *args, **kwargs)
            return subprocess.CompletedProcess(args[0], next(outcomes))
        with patch.object(resume.time, 'monotonic', side_effect=lambda: elapsed[0]), \
             patch.object(resume.time, 'sleep', side_effect=sleep), \
             patch.object(subprocess, 'run', side_effect=probe) as query, \
             patch.object(subprocess, 'check_output') as sessions, \
             patch.object(resume, 'post_spawn') as post, \
             contextlib.redirect_stdout(io.StringIO()):
            code = resume.daemon_preflight(self.state, self.proc)
        sessions.assert_not_called()
        post.assert_not_called()
        self.assertEqual(self.claims(), [])
        return code, query, elapsed[0]

    def gate_results(self):
        return [json.loads(p.read_text()) for p in
                (self.state / 'resume-startup-gates').glob('*.json')]

    def test_gate_unarmed_same_boot_and_mismatched_trial_are_immediate_noops(self):
        for case in ['missing', 'same-boot', 'unarmed-trial', 'wrong-release', 'wrong-attempt']:
            with self.subTest(case=case):
                self.arm_trial()
                self.record['server_url'] = 'http://happy.example.test'
                self.write_marker()
                (self.proc / 'sys/kernel/random/boot_id').write_text('recovery-boot')
                if case == 'missing':
                    self.marker.unlink()
                elif case == 'same-boot':
                    (self.proc / 'sys/kernel/random/boot_id').write_text('preboot')
                elif case == 'unarmed-trial':
                    self.record.pop('expected_trial_attempt')
                    self.write_marker()
                elif case == 'wrong-release':
                    (self.proc / 'sys/kernel/osrelease').write_text(TRIAL_RELEASE + '-other')
                elif case == 'wrong-attempt':
                    (self.proc / 'cmdline').write_text('spx_boot=mainline-trial spx_attempt=other')
                code, probe, elapsed = self.run_gate()
                self.assertEqual((code, elapsed), (0, 0))
                probe.assert_not_called()
                self.assertEqual(self.gate_results(), [])

    def test_gate_matching_trial_waits_then_preserves_marker_and_claim_state(self):
        self.arm_trial()
        self.record['server_url'] = 'http://happy.example.test'
        self.write_marker()
        original = self.marker.read_bytes()
        code, probe, elapsed = self.run_gate([75, 75, 0])
        self.assertEqual((code, elapsed, probe.call_count), (0, 10, 3))
        self.assertEqual(probe.call_args.args[0][-2:], ['--check-server', self.record['server_url']])
        self.assertEqual(probe.call_args.kwargs['timeout'], 5)
        self.assertEqual(self.gate_results()[0]['status'], 'ready')
        self.assertEqual(self.gate_results()[0]['attempt'], TRIAL_ATTEMPT)
        self.assertEqual(self.marker.read_bytes(), original)
        self.assertFalse((self.state / 'resume-ack.json').exists())

    def test_gate_hung_dns_is_bounded_and_allows_daemon_after_deadline(self):
        self.record['server_url'] = 'http://happy.example.test'
        self.write_marker()
        def hang(elapsed, *args, **kwargs):
            self.assertLessEqual(kwargs['timeout'], 5)
            elapsed[0] += kwargs['timeout']
            raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
        code, probe, elapsed = self.run_gate(probe_effect=hang)
        self.assertEqual((code, elapsed), (0, 180))
        self.assertEqual(self.gate_results()[0]['status'], 'timed-out')
        self.assertTrue(self.marker.exists())

    def test_gate_requires_explicit_plain_server_origin(self):
        code, probe, elapsed = self.run_gate()
        self.assertEqual((code, elapsed), (0, 0))
        probe.assert_not_called()
        self.assertEqual(self.gate_results(), [])
        self.record['server_url'] = 'http://user:secret@happy.example.test'
        self.write_marker()
        code, probe, elapsed = self.run_gate()
        self.assertEqual((code, elapsed), (0, 0))
        probe.assert_not_called()
        result = self.gate_results()[0]
        self.assertEqual(result['status'], 'invalid-server-url')
        self.assertNotIn('secret', json.dumps(result))

    def test_gate_marker_removal_releases_wait(self):
        self.record['server_url'] = 'http://happy.example.test'
        self.write_marker()
        def remove(elapsed, *args, **kwargs):
            self.marker.unlink()
            return subprocess.CompletedProcess(args[0], 75)
        code, probe, elapsed = self.run_gate(probe_effect=remove)
        self.assertEqual((code, elapsed, probe.call_count), (0, 5, 1))
        self.assertEqual(self.gate_results()[0]['status'], 'disarmed')

    def test_gate_evidence_failure_does_not_block_daemon(self):
        self.record['server_url'] = 'http://happy.example.test'
        self.write_marker()
        with patch.object(resume, 'save_request', side_effect=OSError('read-only state')):
            code, probe, elapsed = self.run_gate()
        self.assertEqual(code, 0)
        self.assertTrue(self.marker.exists())

    def test_no_marker_is_noop(self):
        self.marker.unlink()
        code, query, post = self.run_helper()
        self.assertEqual(code, 0)
        query.assert_not_called()
        post.assert_not_called()

    def test_preboot_and_experimental_boot_are_noops(self):
        for boot, cmdline in [('preboot', 'spx_boot=known-good'),
                              ('recovery-boot', 'spx_boot=known-good-extra'),
                              ('recovery-boot', 'spx_attempt=trial-a')]:
            with self.subTest(boot=boot, cmdline=cmdline):
                (self.proc / 'sys/kernel/random/boot_id').write_text(boot)
                (self.proc / 'cmdline').write_text(cmdline)
                result = self.run_helper()
                self.assert_no_spawn(*result, expected=0)
                result[1].assert_not_called()

    def test_matching_ack_is_noop_without_consuming_marker(self):
        (self.state / 'resume-ack.json').write_text(json.dumps(
            {'attempt': 'trial-a', 'boot_id': 'recovery-boot'}))
        result = self.run_helper()
        self.assert_no_spawn(*result, expected=0)
        result[1].assert_not_called()

    def test_explicitly_matching_trial_can_resume_same_session(self):
        self.arm_trial()
        code, query, post = self.run_helper()
        self.assertEqual(code, 0)
        post.assert_called_once()
        self.assertEqual(json.loads(post.call_args.args[0].data)['sessionId'], 'session-a')
        self.assertEqual(json.loads(self.claims()[0].read_text())['attempt'], TRIAL_ATTEMPT)
        self.assertTrue(self.marker.exists())

    def test_unarmed_trial_remains_noop(self):
        (self.proc / 'cmdline').write_text('spx_boot=mainline-trial spx_attempt=trial-a')
        result = self.run_helper()
        self.assert_no_spawn(*result, expected=0)
        result[1].assert_not_called()

    def test_trial_marker_requires_both_exact_expected_fields(self):
        for changes in [{'expected_trial_release': None}, {'expected_trial_attempt': None},
                        {'expected_trial_attempt': 'another-attempt'},
                        {'expected_trial_release': TRIAL_RELEASE + '-other'},
                        {'attempt': 'another-attempt'}]:
            with self.subTest(changes=changes):
                self.arm_trial()
                self.record.update(changes)
                self.write_marker()
                result = self.run_helper()
                self.assert_no_spawn(*result, expected=0)
                result[1].assert_not_called()

    def test_trial_kernel_and_command_line_must_match_unambiguously(self):
        for release, cmdline in [
            (TRIAL_RELEASE + '-other', f'spx_boot=mainline-trial spx_attempt={TRIAL_ATTEMPT}'),
            (TRIAL_RELEASE, f'spx_boot=mainline-trial spx_attempt={TRIAL_ATTEMPT}-other'),
            (TRIAL_RELEASE, f'spx_boot=other spx_attempt={TRIAL_ATTEMPT}'),
            (TRIAL_RELEASE, 'spx_boot=mainline-trial'),
            (TRIAL_RELEASE, f'spx_boot=mainline-trial spx_boot=known-good spx_attempt={TRIAL_ATTEMPT}'),
            (TRIAL_RELEASE, f'spx_boot=mainline-trial spx_attempt={TRIAL_ATTEMPT} spx_attempt=other')]:
            with self.subTest(release=release, cmdline=cmdline):
                self.arm_trial()
                (self.proc / 'cmdline').write_text(cmdline)
                (self.proc / 'sys/kernel/osrelease').write_text(release + '\n')
                result = self.run_helper()
                self.assert_no_spawn(*result, expected=0)
                result[1].assert_not_called()

    def test_armed_trial_still_requires_new_boot(self):
        self.arm_trial()
        (self.proc / 'sys/kernel/random/boot_id').write_text('preboot\n')
        result = self.run_helper()
        self.assert_no_spawn(*result, expected=0)
        result[1].assert_not_called()

    def test_armed_trial_ack_and_live_session_guards_remain_active(self):
        self.arm_trial()
        (self.proc / '123').mkdir()
        (self.proc / '123/cmdline').write_bytes(b'happy\0codex\0--happy-session-id\0session-a\0')
        self.assert_no_spawn(*self.run_helper([{'happySessionId': 'session-a', 'pid': 123}]))
        (self.state / 'resume-ack.json').write_text(json.dumps(
            {'attempt': TRIAL_ATTEMPT, 'boot_id': 'recovery-boot'}))
        result = self.run_helper()
        self.assert_no_spawn(*result, expected=0)
        result[1].assert_not_called()

    def test_armed_trial_still_does_not_resubmit_ambiguous_post(self):
        self.arm_trial()
        code, query, post = self.run_helper(post_effect=TimeoutError('response lost'))
        self.assertEqual(code, 75)
        post.assert_called_once()
        code, query, post = self.run_helper()
        self.assertEqual(code, 75)
        post.assert_not_called()

    def test_trial_authorization_preserves_known_good_recovery(self):
        self.arm_trial()
        (self.proc / 'cmdline').write_text('spx_boot=known-good')
        (self.proc / 'sys/kernel/osrelease').write_text('known-good-kernel\n')
        code, query, post = self.run_helper()
        self.assertEqual(code, 0)
        post.assert_called_once()

    def test_stale_ack_does_not_prevent_launch(self):
        for index, change in enumerate([{'attempt': 'old-trial'}, {'boot_id': 'old-boot'},
                                        {'session_id': 'another-session'}]):
            with self.subTest(change=change):
                self.record['attempt'] = f'trial-{index}'
                self.write_marker()
                ack = {'attempt': self.record['attempt'], 'boot_id': 'recovery-boot', **change}
                (self.state / 'resume-ack.json').write_text(json.dumps(ack))
                code, query, post = self.run_helper()
                self.assertEqual(code, 0)
                post.assert_called_once()

    def test_alive_session_without_ack_defers(self):
        (self.proc / '123').mkdir()
        (self.proc / '123/cmdline').write_bytes(b'happy\0codex\0--happy-session-id\0session-a\0')
        original = self.marker.read_bytes()
        self.assert_no_spawn(*self.run_helper(
            [{'happySessionId': 'session-a', 'pid': 123, 'ready': False}]))
        self.assertEqual(self.marker.read_bytes(), original)

    def test_unknown_session_state_defers(self):
        self.assert_no_spawn(*self.run_helper(query_effect=subprocess.TimeoutExpired('happy', 15)))

    def test_happy_empty_list_prose_allows_resume(self):
        code, query, post = self.run_helper(output='No active sessions this daemon is aware of\n')
        self.assertEqual(code, 0)
        post.assert_called_once()
        self.assertTrue(self.marker.exists())

    def test_unavailable_or_malformed_session_response_defers(self):
        for output in ['No daemon running\n', '', 'null', '{}',
                       'No active sessions this daemon is aware of\nUnexpected warning', '[null]']:
            with self.subTest(output=output):
                self.assert_no_spawn(*self.run_helper(output=output))

    def test_reused_session_pid_does_not_block_launch(self):
        (self.proc / '123').mkdir()
        for index, argv in enumerate([b'unrelated\0session-a\0',
                                     b'happy\0codex\0--happy-session-id\0session-a-other\0']):
            with self.subTest(argv=argv):
                self.record['attempt'] = f'trial-{index}'
                self.write_marker()
                (self.proc / '123/cmdline').write_bytes(argv)
                code, query, post = self.run_helper([{'happySessionId': 'session-a', 'pid': 123}])
                self.assertEqual(code, 0)
                post.assert_called_once()

    def test_daemon_post_preserves_identity_and_omits_auth_material(self):
        prompt = self.base / 'custom-prompt.txt'
        prompt.write_text('Inspect trial-a.\nAcknowledge first.\n')
        self.record['prompt_path'] = str(prompt)
        self.write_marker()
        original = self.marker.read_bytes()
        with patch.dict(os.environ, {'HAPPY_RPC_TOKEN': 'do-not-forward', 'HTTP_PROXY': 'http://untrusted.invalid'}):
            code, query, post = self.run_helper([{'happySessionId': 'session-a', 'pid': 456}])
        self.assertEqual(code, 0)
        request = post.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:4567/spawn-session')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), {
            'directory': str(self.base), 'sessionId': 'session-a', 'agent': 'codex',
            'approvedNewDirectoryCreation': False,
            'environmentVariables': {'HAPPY_INITIAL_PROMPT': prompt.read_text()}})
        self.assertEqual(request.header_items(), [('Content-type', 'application/json')])
        self.assertEqual(self.marker.read_bytes(), original)
        self.assertFalse((self.state / 'resume-ack.json').exists())
        self.assertEqual(json.loads(self.claims()[0].read_text())['status'], 'accepted')

    def test_invalid_daemon_identity_does_not_claim(self):
        for daemon in [{'pid': 999, 'httpPort': 0}, {'pid': 999, 'httpPort': 65536},
                       {'pid': 999, 'httpPort': True}, {'pid': True, 'httpPort': 4567},
                       {'pid': 888, 'httpPort': 4567}]:
            with self.subTest(daemon=daemon):
                self.daemon_state.write_text(json.dumps(daemon))
                self.assert_no_spawn(*self.run_helper())

    def test_reused_daemon_pid_does_not_claim(self):
        (self.proc / '999/cmdline').write_bytes(b'unrelated\0daemon\0start-sync\0')
        self.assert_no_spawn(*self.run_helper())

    def test_daemon_change_during_session_query_does_not_claim(self):
        def change(*args, **kwargs):
            self.daemon_state.write_text(json.dumps({'pid': 999, 'httpPort': 5678}))
            return '[]'
        self.assert_no_spawn(*self.run_helper(query_effect=change))

    def test_missing_prompt_or_directory_does_not_claim(self):
        (self.state / 'resume-prompt.txt').write_text(' \n')
        self.assert_no_spawn(*self.run_helper(), expected=78)
        (self.state / 'resume-prompt.txt').write_text('Continue.')
        self.record['directory'] = str(self.base / 'missing')
        self.write_marker()
        self.assert_no_spawn(*self.run_helper(), expected=78)

    def test_startup_network_failure_is_retryable_before_claim(self):
        self.record['server_url'] = 'http://happy.example.test'
        self.write_marker()
        self.assert_no_spawn(*self.run_helper(server_effect=OSError('DNS unavailable')))
        code, query, post = self.run_helper()
        self.assertEqual(code, 0)
        post.assert_called_once()

    def test_invalid_server_origin_does_not_claim(self):
        self.record['server_url'] = 'http://user:secret@happy.example.test'
        self.write_marker()
        self.assert_no_spawn(*self.run_helper(), expected=78)

    def test_claim_precedes_post_and_timeout_is_never_resubmitted(self):
        def timeout(*args, **kwargs):
            claim = json.loads(self.claims()[0].read_text())
            self.assertEqual(claim['status'], 'pending')
            self.assertEqual(claim['attempt'], 'trial-a')
            raise TimeoutError('response lost')
        code, query, post = self.run_helper(post_effect=timeout)
        self.assertEqual(code, 75)
        post.assert_called_once()
        self.assertEqual(json.loads(self.claims()[0].read_text())['status'], 'unconfirmed')
        code, query, post = self.run_helper()
        self.assertEqual(code, 75)
        query.assert_called_once()
        post.assert_not_called()

    def test_unconfirmed_spawn_response_is_never_resubmitted(self):
        for index, response in enumerate([{'success': False, 'sessionId': 'session-a'},
                                         {'success': True, 'sessionId': 'another-session'},
                                         {'success': 1, 'sessionId': 'session-a'}]):
            with self.subTest(response=response):
                self.record['attempt'] = f'trial-{index}'
                self.write_marker()
                code, query, post = self.run_helper(response=response)
                self.assertEqual(code, 75)
                post.assert_called_once()
                code, query, post = self.run_helper()
                self.assertEqual(code, 75)
                post.assert_not_called()

    def test_successful_spawn_is_not_repeated_before_ack(self):
        self.assertEqual(self.run_helper()[0], 0)
        code, query, post = self.run_helper()
        self.assertEqual(code, 0)
        post.assert_not_called()
        self.assertTrue(self.marker.exists())

    def test_malformed_spawn_reply_retains_claim(self):
        code, query, post = self.run_helper(raw_response=b'not JSON')
        self.assertEqual(code, 75)
        post.assert_called_once()
        self.assertEqual(json.loads(self.claims()[0].read_text())['status'], 'unconfirmed')

    def test_simultaneous_helper_defers(self):
        with (self.state / 'resume.lock').open('a') as lock:
            resume.fcntl.flock(lock, resume.fcntl.LOCK_EX | resume.fcntl.LOCK_NB)
            result = self.run_helper()
        self.assert_no_spawn(*result)
        result[1].assert_not_called()


if __name__ == '__main__':
    unittest.main()
