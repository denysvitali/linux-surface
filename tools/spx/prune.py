#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bound SPX diagnostic storage: three attempts, three boot logs.

The default previews deletions; --apply deletes them. Bootable/running attempts
count toward the three slots. The shared build, reusable templates, installed
modules, baseline/recovery payloads and repository result notes are not history.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

KEEP = 3
ID = r'[0-9]{8}(?:[a-z0-9]+|-[0-9]+)'
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
STATE = Path('/var/lib/spx-boot-diagnostics')
UNITS = Path('/etc/systemd/system')
TEMPLATE = STATE / 'template'
BUILD_STAGE = Path('/var/tmp/spx-mainline-trial-20261004bg')
LEGACY_PARENT = Path('/var/tmp/spx-mainline-trial-20261004bf')
LEGACY_RECORD = STATE / 'attempts/20261004bf'
PIN_FILES = [Path('/proc/cmdline'), Path('/etc/grub.d/40_custom'),
             Path('/boot/grub/grub.cfg'), Path('/boot/grub/custom.cfg')]
PIN = re.compile(r'(?:spx_attempt=|spx_baseline=|spx-trial-)(%s)\b' % ID)
ATTEMPT_STORES = [(STATE / 'functional', ''), (STATE / 'attempts', ''),
                  (Path('/var/tmp'), 'spx-mainline-trial-'),
                  (Path('/boot'), 'spx-trial-'),
                  (UNITS, 'spx-trial-return@'), (UNITS, 'spx-trial-check@'),
                  (UNITS / 'timers.target.wants', 'spx-trial-return@'),
                  (UNITS / 'timers.target.wants', 'spx-trial-check@')]
BOOT_STORES = [STATE / 'boots', Path('/boot/spx-diagnostics')]


def seed_template(target=TEMPLATE, parent=LEGACY_PARENT, record=LEGACY_RECORD):
    """Extract only trial inputs, so an old multi-GiB attempt need not live forever."""
    names = ['mkinitcpio.conf', 'initcpio/install/spx_diagnostics',
             'logging/initrd-log.sh', 'logging/initrd-log.service',
             'attempt.json', 'entry.cfg', 'working-recovery.json']
    if target.exists():
        for name in names:
            if not (target / name).is_file() or (target / name).is_symlink():
                raise RuntimeError('incomplete template: ' + str(target / name))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.new')
    # An interrupted extraction must be inspected, not silently overwritten.
    temporary.mkdir(mode=0o700)
    try:
        for name in names:
            source = (record if name in names[-3:] else parent) / name
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        attempt = temporary / 'attempt.json'
        attempt.write_text(json.dumps({'cmdline': json.loads(attempt.read_text())['cmdline']}) + '\n')
        for name in names[:2]:
            path = temporary / name
            text = path.read_text().replace(str(parent), str(target))
            if name == names[1]:
                text = text.replace('mkdir mv cat;', 'mkdir mv cat ls grep rm;')
            path.write_text(text)
        temporary.rename(target)
    except BaseException:
        shutil.rmtree(temporary)
        raise


def entries(directory, prefix):
    pattern = re.compile(re.escape(prefix) + '(%s)(?:[-.].*)?' % ID)
    if directory.is_symlink():
        raise RuntimeError('refusing symlink store: ' + str(directory))
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            match = pattern.fullmatch(path.name)
            if match:
                yield match.group(1), path


def age(path):
    # Unit enablement/drop-in mtimes must not make an old trial look new.
    stamp = path / 'prepared.json'
    return (stamp if not path.is_symlink() and stamp.is_file() else path).lstat().st_mtime


def boot_plan(stores=BOOT_STORES, current=None):
    current = current or Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    doomed = []
    for store in stores:
        if store.is_symlink():
            raise RuntimeError('refusing symlink store: ' + str(store))
        if not store.is_dir():
            continue
        boots = sorted((p for p in store.iterdir() if re.fullmatch(UUID, p.name)),
                       key=age, reverse=True)
        kept = {current}
        for path in boots:
            if len(kept) < KEEP:
                kept.add(path.name)
        doomed.extend(path for path in boots if path.name not in kept)
    return doomed


def plan(incoming=None, protected=(), pin_files=PIN_FILES,
         attempt_stores=ATTEMPT_STORES, boot_stores=BOOT_STORES, template=TEMPLATE):
    pinned = {incoming} if incoming else set()
    if incoming and not re.fullmatch(ID, incoming):
        raise ValueError('invalid incoming attempt')
    for path in pin_files:
        pinned.update(PIN.findall(path.read_text()))  # fail closed on unreadable boot state
    if len(pinned) > KEEP:
        raise RuntimeError('more than three bootable/running attempts; retire stale GRUB entries first')
    protected = {Path(p).absolute() for p in protected} | {BUILD_STAGE}
    if not template.is_dir():
        protected.update([LEGACY_PARENT, LEGACY_RECORD])
    found = [(attempt, path) for store in attempt_stores for attempt, path in entries(*store)]

    def needed(path):
        return any(path == p or path in p.parents for p in protected)

    newest = {}
    # Prefer creation/preparation time in actual attempt stores, not enabled units.
    for attempt, path in found:
        if needed(path):
            continue
        if path.parent in [store[0] for store in attempt_stores[:2]]:
            newest[attempt] = max(newest.get(attempt, 0), age(path))
        else:
            newest.setdefault(attempt, 0)
    kept = set(pinned)
    for attempt in sorted(newest, key=lambda a: (newest[a], a), reverse=True):
        if len(kept) >= KEEP:
            break
        kept.add(attempt)
    doomed = [path for attempt, path in found if attempt not in kept and not needed(path)]
    return kept, doomed + boot_plan(boot_stores)


def remove(path):
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)  # does not traverse symlinks inside an attempt


def prune(apply=False, incoming=None, protected=(), boots_only=False, verbose=True):
    if apply and os.geteuid() != 0:
        raise PermissionError('--apply needs root')
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / '.retention.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if apply and not boots_only:
            seed_template()
        kept, doomed = (set(), boot_plan()) if boots_only else plan(incoming, protected)
        for path in doomed:
            if verbose:
                print(('remove ' if apply else 'would remove ') + str(path), flush=True)
            if apply:
                remove(path)
        if apply and any(path.parent in (UNITS, UNITS / 'timers.target.wants') for path in doomed):
            subprocess.run(['systemctl', 'daemon-reload'], check=True)
        print('%s %d entries; retained attempts: %s' % (
            'Removed' if apply else 'Would remove', len(doomed), ' '.join(sorted(kept)) or 'not applicable'))
        return kept, doomed


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--apply', action='store_true', help='delete; default is preview only')
    parser.add_argument('--boot-logs', action='store_true', help='only rotate per-boot logs')
    args = parser.parse_args()
    try:
        prune(args.apply, boots_only=args.boot_logs)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
