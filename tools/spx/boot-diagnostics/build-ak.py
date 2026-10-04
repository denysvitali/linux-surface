#!/usr/bin/python3
"""Build AK detached BOOST Switch guard from pinned source/config once."""
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

os.umask(0o077)
os.environ['GIT_OPTIONAL_LOCKS'] = '0'
repo = Path('/home/dvitali/Documents/git/linux-surface-next')
stage = Path('/var/tmp/spx-mainline-trial-20260930ak')
boot_id = 'd3b9f9b1-7e95-4963-8225-adf840755102'
release = '7.3.0-rc2-spx-mainline-20260930ak+'
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot_id
assert not (stage / 'build-started.json').exists()
assert (stage / 'logging/initrd-log.sh').is_file()
assert str(stage / 'logging') in (stage / 'initcpio/install/spx_diagnostics').read_text()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

sources = ['sound/soc/codecs/wsa881x.c',
           'drivers/hid/spi-hid/spi-hid-core.c',
           'drivers/hid/spi-hid/spi-hid-core.h',
           'drivers/soundwire/qcom.c',
           'arch/arm64/boot/dts/qcom/sc8180x-wcd9340.dtsi',
           'tools/spx/boot-diagnostics/COMMAND-HISTORY-20260930.md']
source_sha = {name: sha(repo / name) for name in sources}
assert source_sha[sources[0]] == 'e30ce5e45474e472031e647c17577f51547b944aa89292230ac58d169957bcc4'
assert source_sha['drivers/soundwire/qcom.c'] == '33aeace2b61741347c3015affa700c3ca875c6db719d1c19998252948253e83c'
logger_review = json.loads((stage / 'command-source-review/independent-review.json').read_text())
assert source_sha['drivers/soundwire/qcom.c'] == logger_review['driver_sha256']
assert logger_review['native_object_compile_exit_code'] == 0 and logger_review['other_source_diff_chunks_unchanged']
assert logger_review['actual_C_helper_harness_sanitizers_passed']
guard_review = json.loads((stage / 'boost-source-review/independent-review.json').read_text())
assert guard_review['driver_sha256'] == source_sha[sources[0]] and guard_review['exact_C_differential_cases'] == 256
assert guard_review['native_codec_object_compile_exit_code'] == 0 and guard_review['sanitizers_passed']
before = (repo / '.config').read_text()
assert sha(repo / '.config') == '22f5af56d67ed30c8da82b58223dc355164c3ff60f3a09667af7d38189ad6b24'
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
diff = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=repo)
(stage / 'source-ready.json').write_text(json.dumps({'boot_id': boot_id,
    'commit': commit, 'config_sha256': sha(repo / '.config'),
    'source_sha256': source_sha, 'bounded_command_diag_default_off': True, 'command_history_records': 16, 'command_history_dumps': 2, 'bounded_enum_diag_default_off': True, 'startup_diag_windows': 8, 'startup_diag_events_per_window': 48}, indent=2) + '\n')
(stage / 'build-started.json').write_text(json.dumps({'boot_id': boot_id,
    'release': release, 'start_time': time.time()}, indent=2) + '\n')
records = []

def run(args, name):
    start = time.monotonic()
    with (stage / name).open('wb') as stream:
        result = subprocess.run(args, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
    records.append({'args': args, 'log': name, 'exit_code': result.returncode,
                    'seconds': round(time.monotonic() - start, 2)})
    (stage / 'build-commands.json').write_text(json.dumps(records, indent=2) + '\n')
    assert result.returncode == 0, name
    print(name, 'passed', flush=True)

run(['scripts/config', '--file', '.config', '--set-str', 'LOCALVERSION',
     '-spx-mainline-20260930ak'], 'config-set.log')
run(['make', 'olddefconfig'], 'config.log')
after = (repo / '.config').read_text()
removed = set(before.splitlines()) - set(after.splitlines())
added = set(after.splitlines()) - set(before.splitlines())
assert removed == {'CONFIG_LOCALVERSION="-spx-mainline-20260930aj"'}, removed
assert added == {'CONFIG_LOCALVERSION="-spx-mainline-20260930ak"'}, added
(stage / 'config-delta.json').write_text(json.dumps({'removed': sorted(removed),
    'added': sorted(added)}, indent=2) + '\n')
run(['make', 'prepare'], 'prepare.log')
assert subprocess.check_output(['make', '-s', 'kernelrelease'], cwd=repo,
                               text=True).strip() == release
(stage / 'kernel-release.txt').write_text(release + '\n')
(stage / 'source-commit.txt').write_text(commit + '\n')
(stage / 'source.diff').write_bytes(diff)
(stage / 'source-status.txt').write_bytes(subprocess.check_output(
    ['git', 'status', '--short', '--untracked-files=all'], cwd=repo))
shutil.copytree(repo / 'tools/spx/boot-diagnostics', stage / 'diagnostic-sources',
                symlinks=True, ignore=shutil.ignore_patterns('__pycache__'))
for name in ('AGENTS.md', 'LOCAL-PROGRESS.md'):
    shutil.copy2(repo / name, stage / name)
run(['make', '-j6', 'Image', 'qcom/sc8180x-surface-pro-x.dtb'], 'image-dtb.log')
run(['make', '-j6', 'modules'], 'modules.log')
assert (repo / '.config').read_text() == after
assert subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=repo) == diff
for name, digest in source_sha.items():
    assert sha(repo / name) == digest, name
artifacts = stage / 'artifacts'
files = ['.config', 'System.map', 'vmlinux', 'Module.symvers', 'modules.order',
         'arch/arm64/boot/Image',
         'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']
files += [str(Path(p).with_suffix('.ko')) for p in (repo / 'modules.order').read_text().splitlines()]
for name in files:
    dst = artifacts / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / name, dst)
with (stage / 'vmlinuz').open('wb') as stream:
    with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as gz:
        with (artifacts / 'arch/arm64/boot/Image').open('rb') as src:
            shutil.copyfileobj(src, gz)
extracted = subprocess.check_output(['scripts/extract-ikconfig',
    str(artifacts / 'arch/arm64/boot/Image')], cwd=repo)
assert extracted == after.encode()
(stage / 'config-extracted').write_bytes(extracted)
(stage / 'build-complete.json').write_text(json.dumps({'release': release,
    'modules': len(files) - 7, 'embedded_config_exact': True,
    'source_unchanged_during_build': True,
    'config_only_localversion_changed': True,
    'source_sha256': source_sha}, indent=2) + '\n')
shutil.copy2(__file__, stage / 'build.py')
print('AK kernel, DTB, and modules built', flush=True)
