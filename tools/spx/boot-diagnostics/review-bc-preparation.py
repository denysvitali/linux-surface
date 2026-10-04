#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify BC before deployment, preserving BB's actual return."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import bb_boot_guard as parent

REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
spec = importlib.util.spec_from_file_location('fresh_ba_guard', REPO / 'tools/spx/boot-diagnostics/bc_boot_guard.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def read(path):
    return json.loads(path.read_text())


def main():
    assert os.geteuid() == 0
    a = parent.load()
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid == 'e00a2d25-03f7-4265-b56e-0eac05b234d3' and os.uname().release == '6.18.3-1-surface+'
    assert not parent.recovery(a).get('next_entry', '')
    parent.artifacts(a)
    review = read(g.X / 'archive-review.json')
    assert review['boot_id'] == bid and review['module_count'] == 202
    assert review['actual_of_fallback_alias_resolves'] and review['boot_dtb_exact_parent_bb']
    assert g.sha(g.X / 'build-sha256.json') == review['build_manifest_sha256']
    assert g.sha(g.X / 'preparation-sha256.json') == review['preparation_manifest_sha256']
    build, prep = g.files(g.X / 'build'), g.files(g.X / 'preparation')
    assert build == read(g.X / 'build-sha256.json') and len(build) == review['build_files']
    assert prep == read(g.X / 'preparation-sha256.json') and len(prep) == review['preparation_files']
    assert g.links(g.X / 'build') == read(g.X / 'build-symlinks.json')
    assert g.sha(g.X / 'working-recovery.json') == g.sha(parent.X / 'working-recovery.json')
    modules = g.X / 'build/module-root/lib/modules/7.3.0-rc2-spx-mainline-20261004bc+'
    assert g.files(modules) == read(g.X / 'build/module-sha256.json') and len(g.files(modules)) == 217
    assert g.links(modules) == read(g.X / 'build/module-links.json')
    alias = read(g.X / 'build/videocc-alias-resolution.json')
    resolved = subprocess.check_output(['modprobe', '--resolve-alias', '-d', str(g.X / 'build/module-root'),
        '-S', '7.3.0-rc2-spx-mainline-20261004bc+', alias['modalias']], text=True).splitlines()
    assert resolved == alias['modules'] == ['videocc_sm8150']
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics/video-power-20261003'))
    from video_dt_contract import validate
    validate((g.X / 'build/dtb-build/spx.dtb').read_bytes())
    validate((g.X / 'build/artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb').read_bytes())
    assert review['provider_argument_counts_and_interconnect_tags_verified']
    paths = g.source()
    assert paths == 84669
    fixture = Path('/var/lib/spx-boot-diagnostics/fixtures/video-media-20261003')
    assert g.sha(fixture / 'sha256.json') == '3a251cbe1a6d72a1601011d260a85f4faaa6519e111ff97ca0d824f68d0aa612'
    assert g.files(fixture) == read(fixture / 'sha256.json') | {'sha256.json': g.sha(fixture / 'sha256.json')}
    assert not (g.X / 'attempt.json').exists()
    assert not Path('/boot/spx-trial-20261004bc').exists()
    assert not Path('/usr/lib/modules/7.3.0-rc2-spx-mainline-20261004bc+').exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert not parent.recovery(a).get('next_entry', '')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=bid,
                  archive_review_sha256=g.sha(g.X / 'archive-review.json'),
                  source_paths_checked=paths, build_files_checked=len(build),
                  preparation_files_checked=len(prep), module_files_checked=217,
                  of_alias_resolves=True, dtb_provider_contract_verified=True,
                  media_fixture_files_checked=45, installed=False, boot_selected=False,
                  hardware_acceptance_closed=False)
    with (g.X / 'independent-preparation-review.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
