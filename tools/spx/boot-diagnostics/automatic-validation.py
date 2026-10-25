#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install and run the same safe automatic validator on every SPX boot."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LAYOUTS = {
    'standalone': Path('/usr/local/lib/spx-boot-diagnostics'),
    'packaged': Path('/usr/lib/spx-boot-tools'),
}
CONFIG = Path('/etc/spx/hw-validation.json')
BASE = Path('/var/lib/spx-boot-diagnostics')
UNIT = 'spx-hw-validation.service'
DEFERRED = 75
DEFAULT_NETWORK_WAIT_SECONDS = 90
MAX_NETWORK_WAIT_SECONDS = 300


def layout_directory(settings, selected=None):
    layout = selected if selected is not None else settings.get('layout')
    if not isinstance(layout, str) or layout not in LAYOUTS:
        raise ValueError('select --layout standalone or packaged explicitly; '
                         'no installed layout is assumed')
    return layout, LAYOUTS[layout]


def atomic_text(path, text, mode=0o600):
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text)
    temporary.chmod(mode)
    temporary.replace(path)


def runner_status(out, boot_id, kernel, status, detail, exit_code=None,
                  network_wait_seconds=None, network_default_route=None, capture_detail=None):
    if capture_detail is not None:
        detail += " " + capture_detail
    record = dict(boot_id=boot_id, kernel=kernel,
                  utc=datetime.now(timezone.utc).isoformat(), status=status,
                  detail=detail, exit_code=exit_code)
    if network_wait_seconds is not None:
        record['network_wait_seconds'] = network_wait_seconds
        record['network_default_route_at_suite_start'] = network_default_route
    atomic_text(out / 'runner.json', json.dumps(record, indent=2) + '\n')
    atomic_text(out / 'runner.md',
                '# Per-boot automatic validation runner\n\n'
                f'Boot: `{boot_id}`; kernel: `{kernel}`.\n\n'
                f'Runner status: **{status}**. {detail}\n\n'
                + (f'Network readiness wait: {network_wait_seconds:.3f}s; default route at suite start: '
                   f'{"present" if network_default_route else "absent"}.\n\n'
                   if network_wait_seconds is not None else '') +
                'Check results, when available: `report.json` and `report.md`.\n'
                'This runner status is not hardware acceptance.\n')
    print(f'Automatic validator: {status}; {detail}; {out}', flush=True)


def report_stamp(path):
    try:
        info = path.stat()
        return info.st_ino, info.st_mtime_ns, info.st_size
    except FileNotFoundError:
        return None


def parse_default_route(ipv4_text, ipv6_text):
    """Match automaticNetworkDefaultRoute in the Go validator."""
    for line in ipv4_text.splitlines():
        fields = line.split()
        if len(fields) < 8 or fields[1] != '00000000' or fields[7] != '00000000':
            continue
        try:
            flags = int(fields[3], 16)
        except ValueError:
            continue
        if flags & 1 and not flags & 0x200:
            return True
    for line in ipv6_text.splitlines():
        fields = line.split()
        if (len(fields) != 10 or fields[0] != '0' * 32 or fields[1] != '00'):
            continue
        try:
            flags = int(fields[8], 16)
        except ValueError:
            continue
        if flags & 1 and not flags & 0x200:
            return True
    return False


def network_default_route(route_reader=Path.read_text):
    def read(path):
        try:
            return route_reader(Path(path))
        except (OSError, ValueError):
            return ''
    return parse_default_route(read('/proc/net/route'), read('/proc/net/ipv6_route'))


def wait_for_network(seconds=DEFAULT_NETWORK_WAIT_SECONDS, clock=time.monotonic,
                     sleep=time.sleep, route_reader=Path.read_text):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError, OverflowError):
        seconds = DEFAULT_NETWORK_WAIT_SECONDS
    seconds = max(0, min(MAX_NETWORK_WAIT_SECONDS, seconds))
    started = clock()
    deadline = started + seconds
    ready = network_default_route(route_reader)
    while not ready and seconds and clock() < deadline:
        sleep(min(1.0, max(0.0, deadline - clock())))
        ready = network_default_route(route_reader)
    return max(0.0, clock() - started), ready


def run_once(base, runner, repo, boot_id, kernel, execute=subprocess.run, media=None, storage_dir=None, user=None, media_dir=None,
             network_wait_seconds=DEFAULT_NETWORK_WAIT_SECONDS, clock=time.monotonic,
             sleep=time.sleep, route_reader=Path.read_text, camera_capture=False):
    """The Go runner owns the device lock; exit 75 schedules a deferred retry."""
    out = base / 'boots' / boot_id / 'hw-validation'
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Keep completed evidence while a busy lock defers. Only fresh reports count
    # as this invocation's result; Go replaces them atomically after a real run.
    reports = [out / 'report.json', out / 'report.md']
    before = [report_stamp(path) for path in reports]
    if not runner.is_file():
        runner_status(out, boot_id, kernel, 'missing', 'Canonical validator binary is not installed.')
        return 1
    if not os.access(runner, os.X_OK):
        runner_status(out, boot_id, kernel, 'blocked', 'Canonical validator binary is not executable.')
        return 1
    if not repo or not repo.is_dir():
        runner_status(out, boot_id, kernel, 'blocked', 'Validator repository configuration is missing or unavailable.')
        return 1
    # Only an explicit reset request permits the next-boot bootstatus collector.
    # It owns the device lock separately and never rearms the reset experiment.
    pending = base / 'watchdog-reset-pending.json'
    if pending.is_file():
        helper = HERE / 'trial.py'
        if not helper.is_file():
            helper = repo / 'tools/spx/trial.py'
        try:
            attempt = json.loads(pending.read_text())['attempt']
            execute(['/usr/bin/python3', '-B', str(helper), 'watchdog-collect', attempt],
                    check=False, timeout=20)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass  # The row stays blocked; preserve the pending marker for collection.
    waited, route_ready = wait_for_network(network_wait_seconds, clock, sleep, route_reader)
    print(f'Automatic validator network readiness: waited {waited:.3f}s; '
          f'default route at suite start: {"present" if route_ready else "absent"}.', flush=True)
    status_args = dict(network_wait_seconds=waited, network_default_route=route_ready)
    capture_detail = f'Camera capture {"enabled" if camera_capture is True else "disabled"}; microphone capture disabled; no sound authorized.'
    # Include opt-ins in the final status too, not only the transient running record.
    status_args['capture_detail'] = capture_detail
    runner_status(out, boot_id, kernel, 'running', 'Safe automatic checks started.', **status_args)
    try:
        command = [str(runner), '--repo', str(repo), '--output', str(out / 'report'),
                   '--checklist-path', str(out / 'checklist.md')]
        if camera_capture is True:
            command += ['--capture-camera']
        if media is not None:
            command += ['--media', str(media)]
        fixture_dir = media_dir if media_dir is not None else base / 'fixtures/media'
        if media_dir is not None or fixture_dir.is_dir():
            command += ['--media-dir', str(fixture_dir)]
        command += ['--storage-dir', str(storage_dir or base)]
        if user:
            command += ['--user', user]
        completed = execute(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    except PermissionError:
        runner_status(out, boot_id, kernel, 'blocked', 'Permission denied when executing the canonical validator.', **status_args)
        return 1
    except FileNotFoundError:
        runner_status(out, boot_id, kernel, 'missing', 'Canonical validator could not be executed (binary or loader missing).', **status_args)
        return 1
    except OSError as exc:
        runner_status(out, boot_id, kernel, 'failed',
                      f'Canonical validator could not start (OS error {exc.errno}).', **status_args)
        return 1
    if completed.returncode == DEFERRED:
        runner_status(out, boot_id, kernel, 'deferred',
                      'Device lock is busy; systemd will retry this same boot in 60 seconds.', DEFERRED, **status_args)
        return DEFERRED
    if completed.returncode not in (0, 1):
        runner_status(out, boot_id, kernel, 'failed',
                      f'Canonical validator exited with status {completed.returncode}; inspect any retained check report.',
                      completed.returncode, **status_args)
        return 1
    try:
        if any(report_stamp(path) in (None, stamp) for path, stamp in zip(reports, before)):
            raise ValueError('no fresh report')
        report = json.loads(reports[0].read_text())
        if not reports[1].read_text().strip():
            raise ValueError('empty Markdown')
    except (OSError, ValueError):
        runner_status(out, boot_id, kernel, 'failed',
                      'Canonical validator did not produce fresh valid JSON/Markdown reports; retained reports are not this run.',
                      completed.returncode, **status_args)
        return 1
    # Generation validates the saved report against the current catalog; it runs
    # no checks and does not acquire the device lock a second time.
    try:
        generated = execute([str(runner), '--checklist', '--output', str(out / 'report'),
                             '--repo', str(repo), '--require-current-boot'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    except OSError as exc:
        runner_status(out, boot_id, kernel, 'failed',
                      f'Check reports saved, but active repository checklist update could not start (OS error {exc.errno}).',
                      completed.returncode, **status_args)
        return 1
    if generated.returncode != 0:
        runner_status(out, boot_id, kernel, 'failed',
                      f'Check reports saved, but active repository checklist update failed with status {generated.returncode}.',
                      completed.returncode, **status_args)
        return 1
    if completed.returncode == 1:
        detail = 'Automatic checks completed with failed/error outcomes; inspect check reports. Active checklist updated.'
        try:
            counts = report['counts']
            failed, errors = int(counts['failed']), int(counts['errors'])
            detail = f'Automatic checks completed with {failed} failed and {errors} error outcomes. Active checklist updated.'
        except (ValueError, KeyError, TypeError):
            pass
        runner_status(out, boot_id, kernel, 'failed', detail, completed.returncode, **status_args)
        return 1
    runner_status(out, boot_id, kernel, 'succeeded',
                  'Safe automatic checks completed and active checklist updated. Read check results for pass/fail/blocked status.', 0, **status_args)
    return 0


def verify(base, runner, repo, boot_id, execute=subprocess.run):
    """Require complete current-catalog/current-boot evidence, without rerunning tests."""
    out = base / 'boots' / boot_id / 'hw-validation'
    report = out / 'report.json'
    if not repo or not repo.is_dir() or not runner.is_file() or not report.is_file():
        print(f'Current-boot automatic validation is unavailable: {out}. '
              'Inspect runner.json, resolve its prerequisite and run the canonical suite '
              'before selecting another experiment.', file=sys.stderr, flush=True)
        return 1
    result = execute([str(runner), '--from-report', str(report), '--repo', str(repo),
                      '--require-current-boot', '--checklist-path', str(out / 'checklist.md')],
                     check=False)
    return 0 if result.returncode == 0 else 1


def finalize(base, boot_id, kernel, service_result):
    out = base / 'boots' / boot_id / 'hw-validation'
    try:
        status = json.loads((out / 'runner.json').read_text()).get('status')
    except (OSError, ValueError, AttributeError):
        status = None
    if status in ('succeeded', 'failed', 'blocked', 'missing', 'deferred'):
        return
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    runner_status(out, boot_id, kernel, 'failed',
                  f'Runner ended without a completed status; systemd result: {service_result}.')


def replace_asset(source, target, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.new')
    shutil.copyfile(source, temporary)
    temporary.chmod(mode)
    temporary.replace(target)


def install(repo, binary=None, root=Path('/'), control=subprocess.run, media=None, storage_dir=None, user=None, media_dir=None, camera_capture=None, layout=None):
    """Configure one explicit installed layout; enable later boots, never start tests."""
    repo = repo.resolve()
    if not (repo / 'tools/spx/hw-validation/go.mod').is_file():
        raise ValueError('repo must contain tools/spx/hw-validation/go.mod')
    config = root / CONFIG.relative_to('/')
    try:
        retained = json.loads(config.read_text())
        if not isinstance(retained, dict):
            raise ValueError('validator settings must be an object')
    except FileNotFoundError:
        retained = {}
    selected, directory = layout_directory(retained, layout)
    private = root / directory.relative_to('/')
    units = root / 'etc/systemd/system'
    if selected == 'packaged':
        if binary is not None:
            raise ValueError('--binary cannot replace a package-owned validator; rebuild/install spx-boot-tools')
        if (not (private / 'automatic-validation.py').is_file()
                or not (private / 'spx-hw-validation').is_file()
                or not os.access(private / 'spx-hw-validation', os.X_OK)):
            raise ValueError('install spx-boot-tools before selecting the packaged layout')
        unit = (units / UNIT).read_text()
        commands = (f'ExecStart=/usr/bin/python3 -B {directory}/automatic-validation.py run',
                    f'ExecStopPost=/usr/bin/python3 -B {directory}/automatic-validation.py finalize')
        if any(command not in unit.splitlines() for command in commands):
            raise ValueError('migrate the spx-system-config validator unit before selecting the packaged layout')
    else:
        if binary is not None and (not binary.is_file() or not os.access(binary, os.X_OK)):
            raise ValueError('--binary must name a prebuilt executable; the installer does not build it')
        source_unit = HERE / UNIT
        unit = source_unit.read_text().replace(str(LAYOUTS['packaged']), str(directory))
        target_unit = units / UNIT
        if target_unit.exists() and target_unit.read_text() != unit:
            raise ValueError('existing validator unit differs; migrate its owning package/config explicitly')
        replace_asset(HERE / 'automatic-validation.py', private / 'automatic-validation.py', 0o755)
        # The standalone unit copy is private; the /etc unit may be package-owned.
        (private / UNIT).parent.mkdir(parents=True, exist_ok=True)
        atomic_text(private / UNIT, unit, 0o644)
        if not target_unit.exists():
            target_unit.parent.mkdir(parents=True, exist_ok=True)
            atomic_text(target_unit, unit, 0o644)
        if binary is not None:
            replace_asset(binary, private / 'spx-hw-validation', 0o755)
    config.parent.mkdir(parents=True, exist_ok=True)
    settings = dict(repo=str(repo), layout=selected)
    retained_media = retained.get('media')
    retained_media_dir = retained.get('media_dir')
    retained_storage = retained.get('storage_dir')
    retained_user = retained.get('user')
    retained_network_wait = retained.get('network_wait_seconds', DEFAULT_NETWORK_WAIT_SECONDS)
    retained_camera_capture = retained.get('camera_capture') is True
    settings['camera_capture'] = retained_camera_capture if camera_capture is None else camera_capture is True
    settings['storage_dir'] = str(storage_dir) if storage_dir else retained_storage or str(BASE)
    settings['network_wait_seconds'] = max(0, min(MAX_NETWORK_WAIT_SECONDS,
        int(retained_network_wait) if str(retained_network_wait).lstrip('-').isdigit()
        else DEFAULT_NETWORK_WAIT_SECONDS))
    if user or retained_user:
        settings['user'] = user or retained_user
    if media is not None:
        settings['media'] = str(media.resolve())
    elif retained_media:
        settings['media'] = retained_media
    if media_dir is not None:
        settings['media_dir'] = str(media_dir.resolve())
    elif retained_media_dir:
        settings['media_dir'] = retained_media_dir
    atomic_text(config, json.dumps(settings, indent=2) + '\n')
    if root == Path('/'):
        control(['systemctl', 'daemon-reload'], check=True)
        control(['systemctl', 'enable', UNIT], check=True)
    else:
        wants = units / 'multi-user.target.wants'
        wants.mkdir(parents=True, exist_ok=True)
        link = wants / UNIT
        if not link.exists():
            link.symlink_to('../' + UNIT)
    print(f'Installed {UNIT}; enabled for future boots, not started. '
          'No boot selection or trial timers changed.', flush=True)
    if not (private / 'spx-hw-validation').is_file():
        print('Canonical binary is missing; each boot will record an explicit missing runner status.', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    stage = sub.add_parser('install', help='install a prebuilt validator and enable future boot checks')
    stage.add_argument('--repo', type=Path, required=True)
    stage.add_argument('--binary', type=Path, help='prebuilt validator for the standalone layout only')
    stage.add_argument('--layout', choices=tuple(LAYOUTS), help='explicit installed layout; otherwise retain the configured selection')
    stage.add_argument('--media', type=Path, help='explicit verified decoder fixture, never captured media')
    stage.add_argument('--media-dir', type=Path, help='directory of verified per-codec decoder fixtures')
    stage.add_argument('--storage-dir', type=Path, help='bounded disposable I/O directory; default persistent diagnostic directory')
    stage.add_argument('--user', help='explicit user account for user-session checks; root probes remain root')
    stage.add_argument('--root', type=Path, default=Path('/'), help='fixture/staging root; no systemctl when not /')
    capture = stage.add_mutually_exclusive_group()
    capture.add_argument('--camera-capture', dest='camera_capture', action='store_true', default=None, help='enable discarded camera frames on future boot checks; no microphone or sound')
    capture.add_argument('--no-camera-capture', dest='camera_capture', action='store_false', help='disable camera capture on future boot checks')
    run = sub.add_parser('run', help='run once on the current boot (camera capture follows settings; microphone disabled)')
    run.add_argument('--config', type=Path, default=CONFIG)
    run.add_argument('--base', type=Path, default=BASE)
    run.add_argument('--runner', type=Path, help='explicit runner override; otherwise use the configured layout')
    check = sub.add_parser('verify', help='require this boot\'s complete canonical report; no tests run')
    check.add_argument('--config', type=Path, default=CONFIG)
    check.add_argument('--base', type=Path, default=BASE)
    check.add_argument('--runner', type=Path, help='explicit runner override; otherwise use the configured layout')
    final = sub.add_parser('finalize', help='record an interrupted or crashed wrapper without rerunning checks')
    final.add_argument('--base', type=Path, default=BASE)
    args = parser.parse_args(argv)
    if args.action == 'install':
        if args.root == Path('/') and os.geteuid() != 0:
            parser.error('installation needs root')
        try:
            install(args.repo, args.binary, args.root, media=args.media, storage_dir=args.storage_dir, user=args.user, media_dir=args.media_dir, camera_capture=args.camera_capture, layout=args.layout)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        return 0
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    kernel = Path('/proc/sys/kernel/osrelease').read_text().strip()
    if args.action == 'finalize':
        try:
            finalize(args.base, boot_id, kernel, os.environ.get('SERVICE_RESULT', 'unavailable'))
        except OSError as exc:
            print(f'Automatic validator: failed to finalize boot {boot_id} status '
                  f'(OS error {exc.errno}).', file=sys.stderr, flush=True)
            return 1
        return 0
    media, storage_dir, user, media_dir = None, args.base, None, None
    network_wait_seconds = DEFAULT_NETWORK_WAIT_SECONDS
    camera_capture = False
    settings = {}
    try:
        settings = json.loads(args.config.read_text())
        repo = Path(settings['repo'])
        if settings.get('media'):
            media = Path(settings['media'])
        if settings.get('media_dir'):
            media_dir = Path(settings['media_dir'])
        if settings.get('storage_dir'):
            storage_dir = Path(settings['storage_dir'])
        if settings.get('user'):
            user = settings['user']
        network_wait_seconds = settings.get('network_wait_seconds', DEFAULT_NETWORK_WAIT_SECONDS)
        camera_capture = settings.get('camera_capture') is True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        repo = None
    try:
        runner = args.runner
        if runner is None:
            try:
                _, directory = layout_directory(settings)
                runner = directory / 'spx-hw-validation'
            except (ValueError, AttributeError) as exc:
                if args.action == 'verify':
                    print(f'Automatic validator layout is unavailable: {exc}', file=sys.stderr, flush=True)
                else:
                    out = args.base / 'boots' / boot_id / 'hw-validation'
                    out.mkdir(parents=True, exist_ok=True, mode=0o700)
                    runner_status(out, boot_id, kernel, 'blocked', str(exc))
                return 1
        if args.action == 'verify':
            return verify(args.base, runner, repo, boot_id)
        return run_once(args.base, runner, repo, boot_id, kernel,
                        media=media, storage_dir=storage_dir, user=user, media_dir=media_dir,
                        network_wait_seconds=network_wait_seconds, camera_capture=camera_capture)
    except OSError as exc:
        # A report-directory permission/storage failure is still explicit in the journal.
        print(f'Automatic validator: failed to write boot {boot_id} status '
              f'(OS error {exc.errno}); no hardware result recorded.', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
