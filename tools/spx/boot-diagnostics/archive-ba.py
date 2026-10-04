#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independently verify and archive the fresh BA interconnect-argument candidate."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import az_boot_guard as g

STAGE = Path('/var/tmp/spx-mainline-trial-20261004ba')
X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004ba')
RELEASE = '7.3.0-rc2-spx-mainline-20261004ba+'
BOOT = '19cfd105-9780-4c85-995f-625bb1eb0529'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')


def read(path):
    return json.loads(path.read_text())


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    a = g.load()
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    parent = g.X / 'return-review'
    assert g.files(parent) == read(parent / 'sha256.json') | {'sha256.json': g.sha(parent / 'sha256.json')}
    assert g.sha(parent / 'sha256.json') == '93a321c7f38d352fea5ad7c2d3424988d2c4d9ea519c13412f838badadad5cbb'
    assert read(parent / 'report.json')['returned_boot_id'] == BOOT
    source = read(STAGE / 'source-files.json')
    original = read(g.X / 'build/source-files.json')
    assert set(source) == set(original) and len(source) == 96938
    assert {name for name in source if source[name] != original[name]} == {'arch/arm64/boot/dts/qcom/sc8180x.dtsi'}
    for name, row in source.items():
        path = STAGE / 'source' / name
        if 'sha256' in row:
            assert g.sha(path) == row['sha256'] and path.stat().st_size == row['bytes'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
    seen = set()
    with subprocess.Popen(['zstd', '-dc', str(STAGE / 'source.tar.zst')], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
            for entry in tar:
                if entry.isdir():
                    continue
                name = entry.name.removeprefix('./')
                assert name not in seen and name in source
                seen.add(name)
                row = source[name]
                if entry.issym():
                    assert row == dict(symlink=entry.linkname)
                else:
                    assert entry.isfile() and entry.size == row['bytes'] and entry.mode == row['mode']
                    data = tar.extractfile(entry)
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: data.read(1048576), b''):
                        digest.update(chunk)
                    assert digest.hexdigest() == row['sha256'], name
        assert proc.wait() == 0
    assert seen == set(source)
    assert read(STAGE / 'source-tar.json')['sha256'] == g.sha(STAGE / 'source.tar.zst')
    built, assembled = read(STAGE / 'build-complete.json'), read(STAGE / 'build-verification.json')
    assert built['release'] == assembled['release'] == RELEASE
    assert built['modules'] == assembled['modules'] == 202
    assert built['full_kernel_linked'] and built['loadable_modules_linked'] and built['embedded_config_exact']
    assert assembled['module_tree_files'] == 217 and assembled['embedded_modules'] == 55
    assert assembled['embedded_module_payloads_exact'] and assembled['private_logger_exact']
    assert assembled['actual_of_fallback_alias_resolves'] and assembled['boot_dtb_only_parent_az_interconnect_tag_delta']
    for name, digest in built['artifacts'].items():
        assert g.sha(STAGE / 'artifacts' / name) == digest, name
    for name, digest in assembled['artifacts'].items():
        assert g.sha(STAGE / name) == digest, name
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics/video-power-20261003'))
    from video_dt_contract import validate
    validate((STAGE / 'dtb-build/spx.dtb').read_bytes())
    validate((STAGE / 'artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb').read_bytes())
    assert assembled['provider_argument_counts_and_interconnect_tags_verified']
    sys.path.insert(0, str(REPO / 'tools/spx/boot-diagnostics'))
    from review_aq_dtb_delta_ar import flatten
    import libfdt
    before_raw = (g.X / 'build/dtb-build/spx.dtb').read_bytes()
    after_raw = (STAGE / 'dtb-build/spx.dtb').read_bytes()
    before, after = flatten(before_raw), flatten(after_raw)
    assert set(before) == set(after)
    delta = [(path, prop) for path in before for prop in set(before[path]) | set(after[path])
             if before[path].get(prop) != after[path].get(prop)]
    assert delta == [('/soc@0/video-codec@aa00000', 'interconnects')], delta
    old_tree, new_tree = libfdt.Fdt(before_raw), libfdt.Fdt(after_raw)
    assert old_tree.num_mem_rsv() == new_tree.num_mem_rsv()
    assert all(old_tree.get_mem_rsv(i) == new_tree.get_mem_rsv(i)
               for i in range(old_tree.num_mem_rsv()))
    for name in ('integration-source', 'integration-boot'):
        capsule = STAGE / name
        assert g.files(capsule) == read(capsule / 'sha256.json') | {'sha256.json': g.sha(capsule / 'sha256.json')}
        result = read(capsule / 'result.json')
        assert result['provider_argument_counts_and_paths_verified']
        assert len(result['provider_contract_negative_controls']) == 7
        assert result['native'] == dict(resume_cases=10, sys_init_cases=12, firmware_cases=16)
    assert (REPO / '.config').read_bytes() == (STAGE / 'live-config-before').read_bytes()
    assert g.sha(REPO / 'arch/arm64/boot/dts/qcom/sc8180x.dtsi') == source['arch/arm64/boot/dts/qcom/sc8180x.dtsi']['sha256']
    assert g.sha(REPO / 'arch/arm64/configs/spx.config') == source['arch/arm64/configs/spx.config']['sha256']
    X.mkdir(mode=0o700)
    build = X / 'build'
    shutil.copytree(STAGE, build, symlinks=True,
                    ignore=lambda path, names: {'source', 'work-build'} if Path(path) == STAGE else set())
    modules = build / 'module-root/lib/modules' / RELEASE
    assert g.files(modules) == read(build / 'module-sha256.json')
    assert len(g.files(modules)) == 217
    (build / 'module-links.json').write_text(json.dumps(g.links(modules), indent=2) + '\n')
    preparation = X / 'preparation'
    preparation.mkdir(mode=0o700)
    shutil.copytree(g.X / 'preparation', preparation / 'parent-az', symlinks=True)
    assert g.files(preparation / 'parent-az') == read(g.X / 'preparation-sha256.json')
    shutil.copytree(parent, preparation / 'parent-az-return')
    assert g.files(preparation / 'parent-az-return') == g.files(parent)
    for name in ('interconnect-diagnosis', 'terminal-records',
                 'offline-interconnect-20261004ba', 'offline-ba-runtime-20261004',
                 'retired-av-boot-slot'):
        capsule = g.X / name
        assert g.files(capsule) == read(capsule / 'sha256.json') | {'sha256.json': g.sha(capsule / 'sha256.json')}
        shutil.copytree(capsule, preparation / ('parent-az-' + name))
        assert g.files(preparation / ('parent-az-' + name)) == g.files(capsule)
    fixture_prep = Path('/var/lib/spx-boot-diagnostics/fixtures/video-media-20261003-preparation')
    assert g.sha(fixture_prep / 'sha256.json') == 'bd1778f617c0265860bc4740ad6c5abf912878a5f307c4840c694e070024ea6f'
    assert g.files(fixture_prep) == read(fixture_prep / 'sha256.json') | {'sha256.json': g.sha(fixture_prep / 'sha256.json')}
    shutil.copytree(fixture_prep, preparation / 'media-preparation')
    assert g.files(preparation / 'media-preparation') == g.files(fixture_prep)
    helpers = preparation / 'helpers'
    helpers.mkdir()
    for name in ('build-ba.py', 'assemble-ba.py', 'archive-ba.py'):
        shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, helpers / name)
    for name in ('LOCAL-PROGRESS.md', 'PORT-CHECKLIST.md'):
        shutil.copy2(REPO / name, preparation / name)
    for name in ('RESULT-20261003az.md', 'review-az-result.py'):
        shutil.copy2(REPO / 'tools/spx/boot-diagnostics' / name, preparation / name)
    firmware = Path('/usr/lib/firmware/qcom/msft/surface/pro-x-sq2/qcvss8180.mbn')
    assert g.sha(firmware) == '4e93d34504da96320775476bbd509aa06f985b48fb781d4436c8eb812b929928'
    shutil.copy2(firmware, preparation / 'installed-00042.mbn')
    shutil.copy2(g.X / 'working-recovery.json', X / 'working-recovery.json')
    for name, content in (('build-sha256.json', g.files(build)),
                          ('build-symlinks.json', g.links(build)),
                          ('preparation-sha256.json', g.files(preparation))):
        (X / name).write_text(json.dumps(content, indent=2) + '\n')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), release=RELEASE, boot_id=BOOT,
                  source_files_verified=len(source), source_archive_stream_verified=True,
                  source_delta_files=1, full_kernel_and_modules_linked=True,
                  embedded_config_exact=True, module_count=202, module_tree_files=217,
                  private_initramfs_verified=True, embedded_modules=55,
                  videocc_provider_module_verified=True, actual_of_fallback_alias_resolves=True,
                  boot_dtb_only_parent_az_interconnect_tag_delta=True,
                  provider_argument_counts_and_interconnect_tags_verified=True,
                  source_and_actual_boot_dt_negative_controls=7, native_cases_verified=38,
                  native_hardware_operations=0, parent_attempt='20261003az',
                  parent_return_manifest_sha256=g.sha(parent / 'sha256.json'),
                  build_files=len(g.files(build)), build_links=len(g.links(build)),
                  preparation_files=len(g.files(preparation)),
                  build_manifest_sha256=g.sha(X / 'build-sha256.json'),
                  preparation_manifest_sha256=g.sha(X / 'preparation-sha256.json'),
                  recovery_definition_sha256=g.sha(X / 'working-recovery.json'),
                  installed=False, boot_selected=False, hardware_acceptance_closed=False)
    (X / 'archive-review.json').write_text(json.dumps(report, indent=2) + '\n')
    assert g.files(build) == read(X / 'build-sha256.json')
    assert g.files(preparation) == read(X / 'preparation-sha256.json')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert not g.recovery(a).get('next_entry', '')
    os.sync()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
