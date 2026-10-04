#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Resume Happy on recovery or an explicitly armed, matching trial boot.

The resumed turn must first write resume-ack.json with its attempt and boot_id,
then disable the user unit (without --now), archive and unlink the armed marker.
Process existence is not acknowledgement. Never replace a running session.
Trial boots require expected_trial_release and expected_trial_attempt in the
marker; without both, only spx_boot=known-good is accepted.
"""
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

RETRY = 75
CONFIG_ERROR = 78


def allowed_boot(record, cmdline, proc):
    kinds = [arg.partition('=')[2] for arg in cmdline if arg.startswith('spx_boot=')]
    if kinds == ['known-good']:
        return True
    if kinds != ['mainline-trial']:
        return False
    release = record.get('expected_trial_release')
    attempt = record.get('expected_trial_attempt')
    attempts = [arg.partition('=')[2] for arg in cmdline if arg.startswith('spx_attempt=')]
    if (not isinstance(release, str) or not release or
            attempt != record['attempt'] or attempts != [attempt]):
        return False
    return (proc / 'sys/kernel/osrelease').read_text().rstrip('\n') == release


def parse_sessions(output):
    # Happy 6ada5409b4bc prints prose for an empty list, even with --json.
    # "No daemon running" also exits zero, but must remain a retry condition.
    if output.strip() == 'No active sessions this daemon is aware of':
        return []
    sessions = json.loads(output)
    if not isinstance(sessions, list):
        raise ValueError('unexpected session list')
    return sessions


def daemon_identity(path, proc, happy):
    state = json.loads(path.read_text())
    pid, port = state.get('pid'), state.get('httpPort')
    if (type(pid) is not int or pid <= 0 or
            type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('invalid daemon identity')
    argv = (proc / str(pid) / 'cmdline').read_bytes().split(b'\0')
    if (Path(os.fsdecode(argv[0])).name != happy.name or
            argv[1:3] not in ([b'daemon', b'start-sync'], [b'daemon', b'start-foreground'])):
        raise ValueError('daemon PID no longer belongs to Happy')
    return pid, port


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_spawn(port, payload):
    request = urllib.request.Request(
        f'http://127.0.0.1:{port}/spawn-session',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    # A local daemon request must not be sent through an inherited HTTP proxy
    # or followed to a different endpoint by a redirect.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError('daemon did not return HTTP 200')
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError('oversized daemon response')
        return json.loads(body)


def server_address(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('server_url must be a plain HTTP(S) origin')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return parsed.hostname, port


def check_server(url):
    with socket.create_connection(server_address(url), timeout=5):
        pass


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_request(path, record, *, new=False):
    target = path if new else path.with_suffix('.tmp')
    with target.open('x' if new else 'w') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    if not new:
        os.replace(target, path)
    sync_directory(path.parent)


def armed_boot(state, proc):
    marker = state / 'resume-armed.json'
    if not marker.exists():
        return None
    record = json.loads(marker.read_text())
    for key in ('session_id', 'preboot_id', 'attempt'):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError('missing ' + key)
    boot = (proc / 'sys/kernel/random/boot_id').read_text().strip()
    cmdline = (proc / 'cmdline').read_text().split()
    if boot == record['preboot_id'] or not allowed_boot(record, cmdline, proc):
        return None
    return record, boot


def daemon_preflight(state=None, proc=Path('/proc'), *, timeout=180, interval=5):
    """Bounded network gate before daemon startup, only for an armed new boot.

    Always permit daemon startup. This gate neither launches sessions nor reads
    daemon/session credentials. Probe in a child so DNS lookup cannot exceed the
    overall deadline; socket.create_connection's timeout alone does not bound DNS.
    """
    state = state or Path.home() / '.local/state/spx-port'
    try:
        armed = armed_boot(state, proc)
    except (OSError, ValueError, AttributeError):
        print('No valid armed boot for startup gating; allowing normal Happy startup.', flush=True)
        return 0
    if armed is None:
        return 0
    record, boot = armed
    if 'server_url' not in record:
        print('No explicit Happy server origin for startup gating; allowing normal startup.', flush=True)
        return 0
    started = time.monotonic()
    deadline = started + timeout
    status = 'timed-out'
    try:
        server_address(record['server_url'])
    except (ValueError, TypeError, AttributeError):
        status = 'invalid-server-url'
    else:
        print('Waiting up to 180 seconds for the armed Happy server before daemon startup.', flush=True)
        while (remaining := deadline - time.monotonic()) > 0:
            # Removal, acknowledgement cleanup, or replacement of the marker
            # releases the gate instead of delaying unrelated session startup.
            try:
                if armed_boot(state, proc) != armed:
                    status = 'disarmed'
                    break
            except (OSError, ValueError, AttributeError):
                status = 'disarmed'
                break
            try:
                reply = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), '--check-server', record['server_url']],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=min(5, remaining), check=False)
                if reply.returncode == 0:
                    status = 'ready'
                    break
            except (OSError, subprocess.SubprocessError):
                pass
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
    identity = {'attempt': record['attempt'], 'boot_id': boot, 'session_id': record['session_id']}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    result = {**identity, 'status': status, 'elapsed_seconds': round(time.monotonic() - started, 3)}
    try:
        gates = state / 'resume-startup-gates'
        gates.mkdir(mode=0o700, exist_ok=True)
        sync_directory(state)
        save_request(gates / f'{digest}-{time.monotonic_ns()}.json', result, new=True)
    except OSError:
        print('Cannot save startup gate evidence; allowing normal Happy startup.', flush=True)
    print(f'Happy startup gate: {status}; allowing daemon startup.', flush=True)
    return 0


def resume(state, proc, happy, daemon_state):
    try:
        armed = armed_boot(state, proc)
    except (OSError, ValueError, AttributeError):
        print('Cannot read valid resume marker or boot identity.', flush=True)
        return CONFIG_ERROR
    if armed is None:
        return 0
    record, boot = armed
    ack_path = state / 'resume-ack.json'
    if ack_path.exists():
        try:
            ack = json.loads(ack_path.read_text())
            if (ack.get('attempt') == record['attempt'] and
                    ack.get('boot_id') == boot and
                    ack.get('session_id', record['session_id']) == record['session_id']):
                print('The continuation has acknowledged this boot.', flush=True)
                return 0
        except (OSError, ValueError, AttributeError):
            print('Ignoring an unreadable continuation acknowledgement.', flush=True)

    try:
        daemon = daemon_identity(daemon_state, proc, happy)
        sessions = parse_sessions(subprocess.check_output(
            [str(happy), 'daemon', 'list'], text=True, timeout=15))
        for session in sessions:
            if session.get('happySessionId') != record['session_id']:
                continue
            pid = session.get('pid')
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                raise ValueError('session has no valid pid')
            try:
                args = (proc / str(pid) / 'cmdline').read_bytes()
            except FileNotFoundError:
                continue
            argv = args.split(b'\0')
            identity = record['session_id'].encode()
            # Daemon metadata can survive PID reuse by an unrelated process.
            same_session = any(
                arg == b'--happy-session-id' and argv[index + 1] == identity
                for index, arg in enumerate(argv[:-1]))
            if same_session:
                print('The same session is alive but has not acknowledged this boot; retrying later.',
                      flush=True)
                return RETRY
        if daemon_identity(daemon_state, proc, happy) != daemon:
            raise ValueError('daemon changed while checking sessions')
    except (subprocess.SubprocessError, OSError, ValueError, AttributeError) as exc:
        print(f'Cannot establish Happy session state ({type(exc).__name__}); retrying later.',
              flush=True)
        return RETRY

    identity = {'attempt': record['attempt'], 'boot_id': boot, 'session_id': record['session_id']}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    requests = state / 'resume-spawn-requests'
    request_path = requests / (digest + '.json')
    if request_path.exists():
        try:
            prior = json.loads(request_path.read_text())
            if all(prior.get(key) == value for key, value in identity.items()) and prior.get('status') == 'accepted':
                print('The daemon already accepted this continuation; awaiting its acknowledgement.', flush=True)
                return 0
        except (OSError, ValueError, AttributeError):
            pass
        print('A spawn request already exists for this boot; preserving it for verification, without resubmitting.',
              flush=True)
        return RETRY

    try:
        prompt_path = Path(record.get('prompt_path', state / 'resume-prompt.txt')).expanduser()
        prompt = prompt_path.read_text()
        if not prompt.strip():
            raise ValueError('empty prompt')
        directory = Path(record.get('directory', Path.cwd())).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise ValueError('continuation directory does not exist')
    except (OSError, TypeError, ValueError):
        print('Cannot read a nonempty continuation prompt and existing directory.', flush=True)
        return CONFIG_ERROR
    payload = {'directory': str(directory), 'sessionId': record['session_id'], 'agent': 'codex',
               'approvedNewDirectoryCreation': False,
               'environmentVariables': {'HAPPY_INITIAL_PROMPT': prompt}}
    if 'server_url' in record:
        try:
            check_server(record['server_url'])
        except (ValueError, TypeError, AttributeError):
            print('Invalid server_url in the continuation marker.', flush=True)
            return CONFIG_ERROR
        except OSError:
            print('Happy server DNS/TCP is not ready; retrying before claiming a spawn.', flush=True)
            return RETRY
    # The daemon supplies remote mode, RPC credentials and session encryption.
    # A durable claim before POST prevents retrying an ambiguous timeout.
    requests.mkdir(mode=0o700, exist_ok=True)
    sync_directory(state)
    launch = {**identity, 'status': 'pending', 'daemon_pid': daemon[0], 'daemon_port': daemon[1],
              'directory': str(directory), 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}
    try:
        save_request(request_path, launch, new=True)
    except FileExistsError:
        return RETRY
    print('Requesting the armed session from the local Happy daemon.', flush=True)
    try:
        result = post_spawn(daemon[1], payload)
        if result.get('success') is not True or result.get('sessionId') != record['session_id']:
            raise ValueError('spawn response did not confirm the exact session')
    except (OSError, ValueError, AttributeError, http.client.HTTPException) as exc:
        launch.update(status='unconfirmed', error_type=type(exc).__name__)
        save_request(request_path, launch)
        print('Spawn request was not confirmed; it will not be resubmitted automatically.', flush=True)
        return RETRY
    launch['status'] = 'accepted'
    save_request(request_path, launch)
    print('The daemon accepted the same-session continuation; awaiting its acknowledgement.', flush=True)
    return 0


def main(state=None, proc=Path('/proc'), happy=None, daemon_state=None):
    home = Path.home()
    state = state or home / '.local/state/spx-port'
    happy = happy or home / 'go/bin/happy'
    daemon_state = daemon_state or home / '.happy/daemon.state.json'
    if not (state / 'resume-armed.json').exists():
        return 0
    # Serialize this helper's validation and durable claim.
    with (state / 'resume.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return RETRY
        return resume(state, proc, happy, daemon_state)


if __name__ == '__main__':
    if sys.argv[1:] == ['--daemon-preflight']:
        raise SystemExit(daemon_preflight())
    if len(sys.argv) == 3 and sys.argv[1] == '--check-server':
        try:
            check_server(sys.argv[2])
        except (OSError, ValueError, TypeError, AttributeError):
            raise SystemExit(RETRY)
        raise SystemExit(0)
    if len(sys.argv) != 1:
        raise SystemExit(CONFIG_ERROR)
    raise SystemExit(main())
