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

HERE = Path(__file__).resolve().parent
PRIVATE = Path('/usr/local/lib/spx-boot-diagnostics')
CONFIG = Path('/etc/spx/hw-validation.json')
BASE = Path('/var/lib/spx-boot-diagnostics')
UNIT = 'spx-hw-validation.service'
DEFERRED = 75


def atomic_text(path, text, mode=0o600):
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text)
    temporary.chmod(mode)
    temporary.replace(path)


def runner_status(out, boot_id, kernel, status, detail, exit_code=None):
    record = dict(boot_id=boot_id, kernel=kernel,
                  utc=datetime.now(timezone.utc).isoformat(), status=status,
                  detail=detail, exit_code=exit_code)
    atomic_text(out / 'runner.json', json.dumps(record, indent=2) + '\n')
    atomic_text(out / 'runner.md',
                '# Per-boot automatic validation runner\n\n'
                f'Boot: `{boot_id}`; kernel: `{kernel}`.\n\n'
                f'Runner status: **{status}**. {detail}\n\n'
                'Check results, when available: `report.json` and `report.md`.\n'
                'This runner status is not hardware acceptance.\n')
    print(f'Automatic validator: {status}; {detail}; {out}', flush=True)


def report_stamp(path):
    try:
        info = path.stat()
        return info.st_ino, info.st_mtime_ns, info.st_size
    except FileNotFoundError:
        return None


def run_once(base, runner, repo, boot_id, kernel, execute=subprocess.run, media=None, storage_dir=None, user=None):
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
    runner_status(out, boot_id, kernel, 'running', 'Safe automatic checks started; capture is disabled.')
    try:
        command = [str(runner), '--repo', str(repo), '--output', str(out / 'report'),
                   '--checklist-path', str(out / 'checklist.md')]
        if media is not None:
            command += ['--media', str(media)]
        command += ['--storage-dir', str(storage_dir or base)]
        if user:
            command += ['--user', user]
        completed = execute(command, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    except PermissionError:
        runner_status(out, boot_id, kernel, 'blocked', 'Permission denied when executing the canonical validator.')
        return 1
    except FileNotFoundError:
        runner_status(out, boot_id, kernel, 'missing', 'Canonical validator could not be executed (binary or loader missing).')
        return 1
    except OSError as exc:
        runner_status(out, boot_id, kernel, 'failed',
                      f'Canonical validator could not start (OS error {exc.errno}).')
        return 1
    if completed.returncode == DEFERRED:
        runner_status(out, boot_id, kernel, 'deferred',
                      'Device lock is busy; systemd will retry this same boot in 60 seconds.', DEFERRED)
        return DEFERRED
    if completed.returncode not in (0, 1):
        runner_status(out, boot_id, kernel, 'failed',
                      f'Canonical validator exited with status {completed.returncode}; inspect any retained check report.',
                      completed.returncode)
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
                      completed.returncode)
        return 1
    # Generation validates the saved report against the current catalog; it runs
    # no checks and does not acquire the device lock a second time.
    try:
        generated = execute([str(runner), '--checklist', '--output', str(out / 'report'),
                             '--repo', str(repo)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    except OSError as exc:
        runner_status(out, boot_id, kernel, 'failed',
                      f'Check reports saved, but active repository checklist update could not start (OS error {exc.errno}).',
                      completed.returncode)
        return 1
    if generated.returncode != 0:
        runner_status(out, boot_id, kernel, 'failed',
                      f'Check reports saved, but active repository checklist update failed with status {generated.returncode}.',
                      completed.returncode)
        return 1
    if completed.returncode == 1:
        detail = 'Automatic checks completed with failed/error outcomes; inspect check reports. Active checklist updated.'
        try:
            counts = report['counts']
            failed, errors = int(counts['failed']), int(counts['errors'])
            detail = f'Automatic checks completed with {failed} failed and {errors} error outcomes. Active checklist updated.'
        except (ValueError, KeyError, TypeError):
            pass
        runner_status(out, boot_id, kernel, 'failed', detail, completed.returncode)
        return 1
    runner_status(out, boot_id, kernel, 'succeeded',
                  'Safe automatic checks completed and active checklist updated. Read check results for pass/fail/blocked status.', 0)
    return 0


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


def install(repo, binary=None, root=Path('/'), control=subprocess.run, media=None, storage_dir=None, user=None):
    """Stage prebuilt userspace only. Enable for later boots; never start tests."""
    repo = repo.resolve()
    if not (repo / 'tools/spx/hw-validation/go.mod').is_file():
        raise ValueError('repo must contain tools/spx/hw-validation/go.mod')
    if binary is not None and (not binary.is_file() or not os.access(binary, os.X_OK)):
        raise ValueError('--binary must name a prebuilt executable; the installer does not build it')
    private = root / PRIVATE.relative_to('/')
    units = root / 'etc/systemd/system'
    replace_asset(HERE / 'automatic-validation.py', private / 'automatic-validation.py', 0o755)
    # Retain the source unit beside the wrapper so an installed copy can reinstall.
    replace_asset(HERE / UNIT, private / UNIT, 0o644)
    replace_asset(HERE / UNIT, units / UNIT, 0o644)
    if binary is not None:
        replace_asset(binary, private / 'spx-hw-validation', 0o755)
    config = root / CONFIG.relative_to('/')
    config.parent.mkdir(parents=True, exist_ok=True)
    settings = dict(repo=str(repo))
    try:
        retained = json.loads(config.read_text())
        retained_media = retained.get('media')
        retained_storage = retained.get('storage_dir')
        retained_user = retained.get('user')
    except (OSError, ValueError, AttributeError):
        retained_media, retained_storage, retained_user = None, None, None
    settings['storage_dir'] = str(storage_dir) if storage_dir else retained_storage or str(BASE)
    if user or retained_user:
        settings['user'] = user or retained_user
    if media is not None:
        settings['media'] = str(media.resolve())
    elif retained_media:
        settings['media'] = retained_media
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
    stage.add_argument('--binary', type=Path)
    stage.add_argument('--media', type=Path, help='explicit verified decoder fixture, never captured media')
    stage.add_argument('--storage-dir', type=Path, help='bounded disposable I/O directory; default persistent diagnostic directory')
    stage.add_argument('--user', help='explicit user account for user-session checks; root probes remain root')
    stage.add_argument('--root', type=Path, default=Path('/'), help='fixture/staging root; no systemctl when not /')
    run = sub.add_parser('run', help='run once on the current boot (capture remains disabled)')
    run.add_argument('--config', type=Path, default=CONFIG)
    run.add_argument('--base', type=Path, default=BASE)
    run.add_argument('--runner', type=Path, default=PRIVATE / 'spx-hw-validation')
    final = sub.add_parser('finalize', help='record an interrupted or crashed wrapper without rerunning checks')
    final.add_argument('--base', type=Path, default=BASE)
    args = parser.parse_args(argv)
    if args.action == 'install':
        if args.root == Path('/') and os.geteuid() != 0:
            parser.error('installation needs root')
        install(args.repo, args.binary, args.root, media=args.media, storage_dir=args.storage_dir, user=args.user)
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
    media, storage_dir, user = None, args.base, None
    try:
        settings = json.loads(args.config.read_text())
        repo = Path(settings['repo'])
        if settings.get('media'):
            media = Path(settings['media'])
        if settings.get('storage_dir'):
            storage_dir = Path(settings['storage_dir'])
        if settings.get('user'):
            user = settings['user']
    except (OSError, ValueError, KeyError, TypeError):
        repo = None
    try:
        return run_once(args.base, args.runner, repo, boot_id, kernel,
                        media=media, storage_dir=storage_dir, user=user)
    except OSError as exc:
        # A report-directory permission/storage failure is still explicit in the journal.
        print(f'Automatic validator: failed to write boot {boot_id} status '
              f'(OS error {exc.errno}); no hardware result recorded.', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
