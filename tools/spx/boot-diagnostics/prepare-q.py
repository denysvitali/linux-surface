#!/usr/bin/python3
"""Prepare Q with exact P artifacts; do not select a boot."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

os.umask(0o077)
BASE = Path('/var/lib/spx-boot-diagnostics')
P = BASE / 'attempts/20260922p'
Q = BASE / 'attempts/20260927q'
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
RELEASE = '7.3.0-rc2-spx-mainline-20260922p+'
P_MANIFEST = '84df0c3afb1e75bf374f8f5027285f412539d948c860648ee40541c8cb96447e'
P_RESULT_MANIFEST = 'f8c877eca2f9ed6c83eda59e38096fadce8823f36813488fa409da2814f37550'


def call(*args):
    return subprocess.check_output(args, text=True, timeout=90)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def files(root):
    return {str(path.relative_to(root)) for path in root.rglob('*')
            if path.is_file() and not path.is_symlink()}


def verify(root, manifest):
    assert set(manifest) == files(root)
    for name, digest in manifest.items():
        assert sha(root / name) == digest, name


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    assert os.geteuid() == 0
    assert not Q.exists(), 'Q already exists; inspect before any retry'
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert call('uname', '-r').strip() == '6.18.3-1-surface+'
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    assert float(Path('/proc/uptime').read_text().split()[0]) >= 120
    env = call('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'saved_entry=spx-known-good' in env.splitlines()
    assert not any(x.startswith('next_entry=') and x != 'next_entry='
                   for x in env.splitlines())
    assert 'BootNext:' not in call('efibootmgr')
    assert 'set default="spx-known-good"' in Path('/boot/grub/grub.cfg').read_text()
    old = json.loads((P / 'attempt.json').read_text())
    assert old == json.loads((BASE / 'attempt.json').read_text())
    assert old['attempt'] == '20260922p' and old['release'] == RELEASE
    assert old['authorization']['user_response'] == "Yes. Proceed. Don't ask."
    assert sha(P / 'recovered-final-result/sha256.json') == P_RESULT_MANIFEST
    result_files = json.loads((P / 'recovered-final-result/sha256.json').read_text())
    assert len(result_files) == 304
    verify(P / 'recovered-final-result', result_files | {
        'sha256.json': P_RESULT_MANIFEST})
    prior = json.loads((P / 'recovered-final-result/result.json').read_text())
    assert prior['boot_id'] == '35a3d9e0-4a7d-4246-a762-3f5c1e807bda'
    assert prior['last_collected_uptime_seconds'] >= 600
    assert prior['recovery_return_performed'] is True
    assert sha(P / 'build-sha256.json') == P_MANIFEST
    build_manifest = json.loads((P / 'build-sha256.json').read_text())
    assert len(build_manifest) == 985
    verify(P / 'build', build_manifest)
    module_manifest = json.loads((P / 'build/module-sha256.json').read_text())
    modules = Path('/usr/lib/modules') / RELEASE
    assert len(module_manifest) == 202
    verify(modules, module_manifest)
    assert sha(REPO / '.config') == 'ae2115043d59097edb445500fbd0eac81e92279afc76ab6de223bea253640fcb'
    assert sha(REPO / 'drivers/slimbus/qcom-ngd-ctrl.c') == '364357cf6f2097185b66808dc59497cf6e6ed349fbdd9e8e679530581d298b0b'
    assert call('git', '-C', str(REPO), 'rev-parse', 'HEAD').strip() == old['source_commit']
    for name, digest in (old['sha256'] | old['recovery_sha256'] | old['runtime_sha256']).items():
        assert sha(Path(name)) == digest, name
    new_runtime = {
        '/usr/local/lib/spx-boot-diagnostics/q-finalize.py': REPO / 'tools/spx/boot-diagnostics/q-finalize.py',
        '/etc/systemd/system/spx-q-finalize.service': REPO / 'tools/spx/boot-diagnostics/q-finalize.service',
        '/etc/systemd/system/spx-q-finalize.timer': REPO / 'tools/spx/boot-diagnostics/q-finalize.timer',
        '/etc/systemd/system/spx-q-fallback.service': REPO / 'tools/spx/boot-diagnostics/q-fallback.service',
        '/etc/systemd/system/spx-q-fallback.timer': REPO / 'tools/spx/boot-diagnostics/q-fallback.timer',
        '/etc/systemd/system/spx-diag-long-return.timer.d/90-q-exclude.conf': REPO / 'tools/spx/boot-diagnostics/q-exclude-long-return.conf',
    }
    for installed, source in new_runtime.items():
        assert sha(Path(installed)) == sha(source), installed
    assert call('systemctl', 'is-enabled', 'spx-q-finalize.timer').strip() == 'enabled'
    assert call('systemctl', 'is-enabled', 'spx-q-fallback.timer').strip() == 'enabled'
    for name in ['spx-q-finalize.timer', 'spx-q-fallback.timer', 'spx-diag-long-return.timer']:
        assert call('systemctl', 'show', name, '-p', 'ActiveState', '--value').strip() != 'active'
    old_tokens = old['cmdline'].split()
    changes = {'spx_attempt=20260922p': 'spx_attempt=20260927q',
               'slim_qcom_ngd_ctrl.spx_stage7_step=6':
               'slim_qcom_ngd_ctrl.spx_stage7_step=7'}
    for before in changes:
        assert old_tokens.count(before) == 1
    new_tokens = [changes.get(token, token) for token in old_tokens]
    assert len(new_tokens) == len(old_tokens)
    assert [(x, y) for x, y in zip(old_tokens, new_tokens) if x != y] == list(changes.items())
    assert new_tokens.count('slim_qcom_ngd_ctrl.spx_pio_cap_retries=0') == 1
    assert new_tokens.count('slim_qcom_ngd_ctrl.spx_pio_mode=1') == 1
    assert new_tokens.count('slim_qcom_ngd_ctrl.spx_probe_stage=7') == 1
    a = json.loads(json.dumps(old))
    a.update({'attempt': '20260927q', 'entry': 'spx-trial-20260927q',
              'preboot_id': bid, 'parent_attempt': '20260922p',
              'build_archive': str(Q / 'build'), 'source_diff': str(Q / 'build/source.diff'),
              'state': 'prepared Q stage7step7 with automatic 620s finalizer; not selected',
              'cmdline': ' '.join(new_tokens),
              'comparison': 'Exact P build, modules, boot payloads and recovery reused; only attempt ID and stage7_step 6 to 7 change. Q waits up to five seconds for reactive capability with proactive retries zero.',
              'instrumentation': 'Automatic 620s finalizer; 900s fallback; old 600s return excluded for Q; no live module parameter or device rebinding.'})
    for key in ['validated_preboot', 'reboot_requested_at', 'continuation']:
        a.pop(key, None)
    a['runtime_sha256'].update({name: sha(Path(name)) for name in new_runtime})
    a['validated_prior_result'] = {'attempt': '20260922p',
                                   'result_path': str(P / 'recovered-final-result/result.json'),
                                   'result_sha256': sha(P / 'recovered-final-result/result.json'),
                                   'manifest_sha256': P_RESULT_MANIFEST}
    entry = call('python3', str(REPO / 'tools/spx/boot-diagnostics/grub-entry.py'),
                 '--attempt', a['attempt'], '--entry', a['entry'],
                 '--kernel', '/spx-trial-20260922p/vmlinuz',
                 '--initrd', '/spx-trial-20260922p/initramfs.img',
                 '--dtb', '/spx-trial-20260922p/spx.dtb', '--cmdline', a['cmdline'])
    Q.mkdir(mode=0o700)
    shutil.copy2(__file__, Q / 'prepare.py')
    shutil.copytree(P / 'build', Q / 'build', symlinks=True)
    shutil.copy2(P / 'build-sha256.json', Q / 'build-sha256.json')
    verify(Q / 'build', build_manifest)
    assert sha(Q / 'build-sha256.json') == P_MANIFEST
    shutil.copy2(P / 'attempt.json', Q / 'origin-attempt.json')
    shutil.copy2(P / 'recovered-final-result/result.json', Q / 'origin-result.json')
    shutil.copy2(P / 'recovered-final-result/sha256.json', Q / 'origin-result-sha256.json')
    shutil.copy2('/boot/grub/custom.cfg', Q / 'custom.cfg.before')
    shutil.copy2('/boot/grub/grub.cfg', Q / 'grub.cfg.before')
    (Q / 'grubenv.before').write_text(env)
    (Q / 'entry.cfg').write_text(entry)
    subprocess.run(['grub-script-check', str(Q / 'entry.cfg')], check=True)
    save(Q / 'attempt.json', a)
    save(Q / 'reused-artifacts.json', {'origin_attempt': '20260922p',
         'release': RELEASE, 'build_manifest_sha256': P_MANIFEST,
         'build_files_verified': len(build_manifest),
         'installed_module_files_verified': len(module_manifest),
         'boot_payloads': a['sha256'], 'recovery_files': a['recovery_sha256'],
         'cmdline_changes': changes, 'new_runtime_files': list(new_runtime)})
    current = Q / 'current-diagnostic-sources'
    current.mkdir()
    for p in (REPO / 'tools/spx/boot-diagnostics').iterdir():
        if p.is_file():
            shutil.copy2(p, current / p.name)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert 'next_entry=' in call('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'BootNext:' not in call('efibootmgr')
    Path('/boot/grub/custom.cfg').write_text(
        '# Authorized one-shot Q capability waiter; exact P artifacts; known-good default.\n' + entry)
    save(BASE / 'attempt.json', a)
    with (Q / 'preflight.log').open('w') as log:
        subprocess.run(['python3', str(REPO / 'tools/spx/boot-diagnostics/preflight.py')],
                       check=True, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    assert 'READ-ONLY PASS' in (Q / 'preflight.log').read_text()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
    assert 'saved_entry=spx-known-good' in call('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'next_entry=' in call('grub-editenv', '/boot/grub/grubenv', 'list')
    assert 'BootNext:' not in call('efibootmgr')
    assert not (Q / 'reboot-requested').exists()
    save(Q / 'preparation-result.json', {'boot_id': bid, 'release': RELEASE,
         'origin_build_files_verified': len(build_manifest),
         'installed_module_files_verified': len(module_manifest),
         'read_only_preflight_passed': True, 'boot_selected': False})
    os.sync()
    print('Q prepared with exact P artifacts and automatic finalizer; no boot selected')


if __name__ == '__main__':
    main()
