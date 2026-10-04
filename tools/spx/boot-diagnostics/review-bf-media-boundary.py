#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal BF's actual media skip against its already reviewed startup identity."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bf_boot_guard as g


def read(path):
    return json.loads(path.read_text())


def sealed(path):
    digest = g.sha(path / 'sha256.json')
    assert g.files(path) == read(path / 'sha256.json') | {'sha256.json': digest}
    return digest


def main():
    os.umask(0o077)
    a = g.load()
    boot = g.trial_identity(a)
    assert boot == 'c202c762-0708-489e-8b80-3b129f0de828'
    startup = read(g.X / 'video-startup/result.json')
    reviewed = read(g.X / 'startup-review/report.json')
    skipped = read(g.X / 'media-not-run.json')
    assert reviewed['boot_id'] == startup['boot_id'] == skipped['boot_id'] == boot
    assert startup['release'] == skipped['release'] == a['release']
    assert skipped['video_startup_sha256'] == g.sha(g.X / 'video-startup/result.json')
    assert skipped['hardware_codec_used'] is False and skipped['media_acceptance_passed'] is False
    assert not reviewed['normal_venus_driver_bound'] and not reviewed['decoder_encoder_nodes_observed']
    assert not startup['video_nodes'] and reviewed['probe_errnos'] == [-110]
    assert reviewed['pas_init_returns'] == reviewed['pas_memory_returns'] == [0]
    assert not (g.X / 'media-short-result').exists()
    out = g.X / 'actual-media-boundary'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    for name in ('media-not-run.json', 'video-startup/result.json', 'startup-review/report.json'):
        shutil.copy2(g.X / name, out / name.replace('/', '-'))
    unit = 'spx-bf-media.service'
    state = dict(line.split('=', 1) for line in g.command('systemctl', 'show', unit,
        '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainStatus',
        '-p', 'InvocationID').splitlines())
    assert state['ActiveState'] == 'inactive' and state['SubState'] == 'dead'
    assert state['Result'] == 'success' and state['ExecMainStatus'] == '0'
    assert state['InvocationID']
    argv = ['journalctl', '-b', boot.replace('-', ''), '-u', unit, '--no-pager', '-o', 'json']
    capture = subprocess.run(argv, capture_output=True, check=True, timeout=30)
    (out / 'media-journal.jsonl').write_bytes(capture.stdout)
    (out / 'media-journal.stderr').write_bytes(capture.stderr)
    entries = [json.loads(line) for line in capture.stdout.splitlines()]
    assert entries and all(row['_BOOT_ID'] == boot.replace('-', '') for row in entries)
    assert any('Finished BF static reservation media.' in row['MESSAGE'] for row in entries)
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=boot, release=a['release'],
        startup_manifest_sha256=sealed(g.X / 'video-startup'),
        startup_review_manifest_sha256=sealed(g.X / 'startup-review'),
        handoff_manifest_sha256=sealed(g.X / 'actual-handoff-records'),
        media_skip_hash_bound_to_actual_startup=True, producer_unit=state,
        media_not_run=True, reason=skipped['reason'], pas_memory_setup_zero_observed=True,
        core_startup_probe_errno=-110, media_acceptance_passed=False,
        hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    sealed(out)
    assert g.trial_identity(a) == boot
    os.sync()
    print(json.dumps(report | dict(manifest_sha256=g.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
