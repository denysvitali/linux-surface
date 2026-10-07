#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stop only the verified desktop audio owner before a guarded trial return."""
import json
import os
from pathlib import Path
import pwd
import re
import select
import signal
import stat
import time


def require(value, message):
    if not value:
        raise RuntimeError(message)


def fault(value):
    if isinstance(value, dict):
        return any(fault(item) for item in value.values())
    if isinstance(value, list):
        return any(fault(item) for item in value)
    return bool(value)


class Live:
    def __init__(self, out, attempt, release, boot, here, user, peak, proc=Path('/proc'),
                 lock=Path('/tmp/spx-locks/spx-device.lock')):
        self.out, self.attempt, self.release, self.boot = out, attempt, release, boot
        self.here, self.user, self.peak, self.proc, self.lock = here, user, peak, proc, lock
        self.fds = []
        self.target = out / 'audio-stop.json'

    def record(self, path):
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and
                metadata.st_mode & 0o022 == 0, 'Unsafe audio evidence: ' + str(path))
        return json.loads(path.read_text())

    def boot_gate(self):
        require(os.geteuid() == 0 and os.uname().release == self.release, 'Wrong root/kernel')
        require((self.proc / 'sys/kernel/random/boot_id').read_text().strip() == self.boot,
                'Boot changed')
        words = (self.proc / 'cmdline').read_text().split()
        require([w for w in words if w.startswith('spx_attempt=')] ==
                ['spx_attempt=' + self.attempt] and 'spx_boot=mainline-functional' in words,
                'Wrong trial')

    def pcm_status(self):
        return {str(path): path.read_text().strip() for pattern in
                ('card*/pcm*p/sub*/status', 'card*/pcm*c/sub*/status')
                for path in (self.proc / 'asound').glob(pattern)}

    def lock_owner(self):
        return (self.lock / 'owner').read_text().strip() if self.lock.exists() else None

    def start(self, pid):
        # comm may contain spaces or parentheses. Field22 follows its last ')'.
        return (self.proc / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]

    def pin(self, pid):
        before = self.start(pid)
        fd = os.pidfd_open(pid)
        self.fds.append(fd)
        require(self.start(pid) == before, 'PID changed while opening pidfd')
        require(not select.select([fd], [], [], 0)[0], 'Audio process already exited')
        return fd

    def validate_owner(self, ready, quiet=False):
        require(ready.get('boot_id') == self.boot and ready.get('release') == self.release,
                'Stale audio readiness')
        require(all(ready.get(k) is True for k in
                    ('acoustic_passed', 'public_acoustic_passed', 'recording_closed')) and
                not ready.get('stopped') and ready.get('sink') == 'spx_speakers',
                'Audio is not verified and serving')
        require(type(self.peak) is int and 1433 <= self.peak <= (1433 if quiet else 12000) and
                ready.get('peak_limit') == self.peak and ready.get('pa_gain') == 0,
                'Unexpected desktop level')
        require(pwd.getpwnam(self.user).pw_uid != 0, 'Desktop user must be unprivileged')
        owner, pcm = ready.get('owner_pid'), ready.get('pcm_pid')
        require(all(type(pid) is int and pid > 1 for pid in (owner, pcm)), 'Invalid audio PIDs')
        command_path = self.proc / str(owner) / 'cmdline'
        raw = command_path.read_bytes()
        command = raw.decode().rstrip('\0').split('\0')
        require(any(path in command for path in (str(self.here / 'audio.py'),
                '/usr/local/lib/spx-boot-diagnostics/audio.py')) and 'serve' in command,
                'Unexpected audio owner command')
        for option, value in (('--owner', 'audio-' + self.attempt),
                              ('--desktop-user', self.user), ('--desktop-peak', str(self.peak)),
                              ('--output', str(self.out / 'audio'))):
            require(command.count(option) == 1 and command.index(option) + 1 < len(command) and
                    command[command.index(option) + 1] == value, 'Wrong audio option: ' + option)
        require(re.search(r'^Uid:\s+0\s+0\s+0\s+0\s*$',
                (self.proc / str(owner) / 'status').read_text(), re.M), 'Audio owner is not root')
        require(self.lock_owner() == 'audio-' + self.attempt, 'Wrong audio device lock')
        require((self.proc / str(pcm) / 'comm').read_text().strip() == 'aplay' and
                re.search(r'^PPid:\s*' + str(owner) + r'\s*$',
                (self.proc / str(pcm) / 'status').read_text(), re.M), 'Wrong native PCM child')
        statuses = self.pcm_status()
        playback = [v for p, v in statuses.items() if re.search(r'/pcm\d+p/', p) and v != 'closed']
        capture = [v for p, v in statuses.items() if re.search(r'/pcm\d+c/', p)]
        require(len(playback) == 1 and re.search(r'^state:\s+RUNNING$', playback[0], re.M) and
                re.search(r'^owner_pid\s*:\s*' + str(pcm) + r'\s*$', playback[0], re.M),
                'Playback is not the matching RUNNING PCM')
        require(capture and all(v == 'closed' for v in capture), 'Capture is not closed')
        identity = dict(owner_pid=owner, pcm_pid=pcm, owner_start=self.start(owner),
                        pcm_start=self.start(pcm), command=command)
        require(command_path.read_bytes() == raw, 'Audio command changed')
        self.boot_gate()
        return identity

    def no_audio(self):
        require(not (self.out / 'audio/serve-ready.json').exists(), 'Unfinished audio readiness')
        require(not (self.lock_owner() or '').startswith('audio-'), 'Audio is starting or unfinished')
        require(all(v == 'closed' for v in self.pcm_status().values()), 'PCM remains open')
        # Historical result files do not identify a live owner. They remain intact.
        return dict(no_active_audio=True, pcms_closed=True, audio_lock_absent=True)

    def validate_final(self, result, identity, requested=True):
        require(result.get('action') == 'serve' and result.get('success') is True and
                not result.get('error') and not result.get('cleanup_errors'), 'Serve failed or cleanup incomplete')
        before, serve = result.get('before', {}), result.get('serve', {})
        require(before.get('boot_id') == self.boot and before.get('release') == self.release and
                serve.get('boot_id') == self.boot and serve.get('release') == self.release,
                'Stale final audio result')
        require(serve.get('owner_pid') == identity['owner_pid'] and
                serve.get('pcm_pid') == identity['pcm_pid'] and
                result.get('pcm', {}).get('pid') == identity['pcm_pid'], 'Final audio identity changed')
        require(serve.get('stopped') is True and serve.get('stop_reason') in
                (('SIGTERM',) if requested else ('SIGTERM', 'deadline')), 'Unconfirmed orderly stop')
        desktop = result.get('desktop', {})
        require(desktop.get('teardown', {}).get('passed') is True and
                desktop.get('graph_restored') is True and not desktop.get('cleanup_error') and
                not desktop.get('monitor_error'), 'Attached teardown or graph restoration failed')
        require(type(result.get('parked_state', {}).get('GPIO_VAL')) is int and
                result['parked_state']['GPIO_VAL'] & 0x1e == 0x18, 'Missing physical parking evidence')
        require(result.get('parked') is True and result.get('recording_closed') is True and
                result.get('runtime_pm', {}).get('restored') is True, 'Parking/recording/PM cleanup incomplete')
        background = result.get('background_errors')
        require(isinstance(background, dict) and
                all(key in background for key in ('capture', 'playback', 'desktop_monitor')) and
                not fault(background), 'Background audio error or missing evidence')
        for name in ('pcm', 'capture'):
            evidence = result.get(name, {})
            require(not evidence.get('error') and isinstance(evidence.get('log'), str) and
                    not re.search(r'xrun|underrun|overrun|error', evidence['log'], re.I),
                    name + ' error or missing final log')
        require(all(item.get('returncode') == 0 for item in result.get('microphone_mixer_restore', [])),
                'Microphone route restoration failed')
        self.boot_gate()
        require(all(v == 'closed' for v in self.pcm_status().values()), 'PCM remains open')
        require(not self.lock.exists(), 'Audio wrapper has not released device lock')
        return dict(serve_success=True, attached_teardown=True, graph_restored=True,
                    parked=True, pcms_closed=True, device_lock_released=True)

    def stop(self):
        self.boot_gate()
        ready_path = self.out / 'audio/serve-ready.json'
        if not ready_path.exists():
            return self.no_audio()
        ready = self.record(ready_path)
        require(ready.get('boot_id') == self.boot and ready.get('release') == self.release,
                'Stale audio readiness; refuse uncertain owner')
        owner, pcm = ready.get('owner_pid'), ready.get('pcm_pid')
        require(all(type(pid) is int and pid > 1 for pid in (owner, pcm)), 'Invalid audio PIDs')
        if not (self.proc / str(owner)).exists():
            require(not (self.proc / str(pcm)).exists(), 'Orphan native PCM child')
            identity = dict(owner_pid=owner, pcm_pid=pcm)
            final = self.record(self.out / 'audio/serve-result.json')
            return dict(identity=identity, already_stopped=True,
                        **self.validate_final(final, identity, requested=False))
        identity = self.validate_owner(ready, quiet=True)
        fd = self.pin(identity['owner_pid'])
        pcm_fd = self.pin(identity['pcm_pid'])
        # Repeat all gates after pinning. No PID-number or process-group signal.
        require(self.validate_owner(self.record(ready_path), quiet=True) == identity,
                'Audio identity changed before stop')
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        self.signalled = identity
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            exited = len(select.select([fd, pcm_fd], [], [], 0)[0]) == 2
            if exited and not self.lock.exists():
                final = self.record(self.out / 'audio/serve-result.json')
                return dict(identity=identity, signal='SIGTERM',
                            **self.validate_final(final, identity))
            time.sleep(0.1)
        raise RuntimeError('Audio stop exceeded 40s; no forced kill or reboot')

    def reuse(self, previous):
        require(previous.get('complete') is True and previous.get('boot_id') == self.boot and
                previous.get('release') == self.release and previous.get('attempt') == self.attempt,
                'Previous stop failed or belongs to another boot; evidence preserved')
        self.boot_gate()
        if previous.get('no_active_audio'):
            self.no_audio()
        else:
            for key in ('owner_pid', 'pcm_pid'):
                require(not (self.proc / str(previous['identity'][key])).exists(),
                        'Recorded audio PID is present again; refuse reuse')
            self.validate_final(self.record(self.out / 'audio/serve-result.json'), previous['identity'],
                                requested=not previous.get('already_stopped'))
        return previous

    def close(self):
        for fd in self.fds:
            os.close(fd)
        self.fds.clear()


def exercise(live):
    if live.target.exists():
        return live.reuse(live.record(live.target))
    result = dict(complete=False, attempt=live.attempt, boot_id=live.boot, release=live.release,
                  scope='guarded-trial-return-only', arbitrary_shutdown_tested=False)
    try:
        result.update(live.stop())
        result['complete'] = True
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        if getattr(live, 'signalled', None):
            result.update(identity=live.signalled, signal='SIGTERM')
    finally:
        live.close()
        with live.target.open('x') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    require(result['complete'], result.get('error', 'Audio stop failed'))
    return result
