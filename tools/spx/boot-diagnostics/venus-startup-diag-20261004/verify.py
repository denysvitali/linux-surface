#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify scoped startup observations using exact BE/candidate C bodies offline."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

HERE = Path(__file__).resolve().parent
WORK = Path('/var/tmp/spx-venus-startup-diag-20261004')
VENUS = 'drivers/media/platform/qcom/venus/'
PINS = {
    'hfi_venus.c': ('f11c3da3bd23f3141dc381dbc0bfe40f7f9b9bbb56e4915f8437b1cb7402935b',
                    '81f98e580caa7919ac28f8b886e67f03386ab4a4f190af463b13e563956fd219'),
    'firmware.c': ('7cba13df11afac8d45dedd4879ee86417d3238771461b3a93cbeb2be9facc708',
                   '59a649500a40f32d67cadef60c42eb76a8e1a32f50d5068b33a2b8ca00145b7e'),
    'firmware.h': ('3eca15719a88e3b73d3ffa7485987d5b327d3b08078a9ec54bbaf8d8f744d693',
                   '67630f28cae81992fff5b2b6ab99f3b1e2f581eb641a32ad91b399ed3e22287a'),
}


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    if source[end:end + 1] == ';':
        end += 1
    return source[start:end]


def read(path):
    return json.loads(path.read_text())


def live(rows, changes):
    checked = 0
    for name, row in rows.items():
        top = Path(name).parts[0]
        if not (top in g.CODE_DIRS or name in g.CODE_TOP or name.startswith('localversion') or
                (top == 'tools' and not name.startswith('tools/spx/boot-diagnostics/')) or
                name == 'Documentation/devicetree/bindings/media/qcom,sc8180x-venus.yaml'):
            continue
        path = g.REPO / name
        if name in changes:
            assert row['sha256'] == changes[name]['before_sha256']
            assert g.sha(path) == changes[name]['after_sha256']
        elif 'sha256' in row:
            assert g.sha(path) == row['sha256'], name
        else:
            assert path.is_symlink() and os.readlink(path) == row['symlink'], name
        checked += 1
    assert checked == 84669
    assert g.sha(g.REPO / '.config') == 'f0c4a7ff7ed3659f1f44ede2348d7333803721b5bc1229d57744f7999e619288'
    return checked


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
    assert not g.recovery(a).get('next_entry', '')
    g.artifacts(a)
    source_manifest = g.X / 'dtb-build/candidate-source-files.json'
    assert g.sha(source_manifest) == 'bb381d622b8089abeb5756ff2430fc1c611f4355118e13eb43143fe90ab21666'
    rows = read(source_manifest)
    out = args.output
    out.mkdir(mode=0o700)
    for name in ('verify.py', 'native.h', 'checks.h', 'README.md'):
        shutil.copy2(HERE / name, out / name)
    before, after, changes, patch = {}, {}, {}, []
    for name, (pre, post) in PINS.items():
        before[name] = (WORK / ('before-' + name)).read_text()
        after[name] = (g.REPO / VENUS / name).read_text()
        assert g.sha(WORK / ('before-' + name)) == rows[VENUS + name]['sha256'] == pre
        assert g.sha(g.REPO / VENUS / name) == post
        changes[VENUS + name] = dict(before_sha256=pre, after_sha256=post)
        delta = list(difflib.unified_diff(before[name].splitlines(keepends=True),
                     after[name].splitlines(keepends=True), fromfile='a/' + VENUS + name,
                     tofile='b/' + VENUS + name))
        assert not any(line.startswith('-') and not line.startswith('---') for line in delta)
        patch.extend(delta)
        (out / ('before-' + name)).write_text(before[name])
        (out / ('linux-' + name)).write_text(after[name])
    (out / 'scoped.diff').write_text(''.join(patch))
    checked = live(rows, changes)
    for name in ('core.h', 'hfi_helper.h', 'hfi_venus_io.h'):
        assert g.sha(g.REPO / VENUS / name) == rows[VENUS + name]['sha256']
        shutil.copy2(g.REPO / VENUS / name, out / ('linux-' + name))
    shutil.copy2(source_manifest, out / 'be-source-files.json')
    shutil.copy2(WORK / 'pre-change.json', out / 'pre-change.json')
    core = (out / 'linux-core.h').read_text()
    helper = (out / 'linux-hfi_helper.h').read_text()
    definitions = block(core, 'enum vpu_version {') + '\n' + block(helper, 'enum hfi_version {')
    definitions += '\n' + core[core.index('#define IS_V1(core)'):core.index('static inline bool is_lite(')]
    definitions += '\n' + after['hfi_venus.c'][after['hfi_venus.c'].index('#define IFACEQ_NUM'):
                                             after['hfi_venus.c'].index('struct iface_queue {')]
    definitions += '\n' + after['firmware.c'][after['firmware.c'].index('#define VENUS_PAS_ID'):
                                            after['firmware.c'].index('static void venus_reset_cpu(')]
    diag = after['hfi_venus.c'][after['hfi_venus.c'].index('static bool spx_hfi_startup_diag;'):
                                after['hfi_venus.c'].index('#define HFI_MASK_QHDR_TX_TYPE')]
    assert diag.startswith('static bool spx_hfi_startup_diag;\n')
    assert 'module_param_named(spx_hfi_startup_diag, spx_hfi_startup_diag, bool, 0400);' in diag
    unchanged = block(after['hfi_venus.c'], 'static u32 venus_hwversion(')
    assert unchanged == block(before['hfi_venus.c'], 'static u32 venus_hwversion(')
    bodies, originals = [], []
    for filename, marker in [('hfi_venus.c', 'static int venus_boot_core('),
                             ('hfi_venus.c', 'static int venus_run('),
                             ('firmware.c', 'int venus_set_hw_state('),
                             ('firmware.c', 'int venus_boot(')]:
        bodies.append(block(after[filename], marker))
        original = block(before[filename], marker)
        for symbol in ('venus_boot_core', 'venus_run', 'venus_set_hw_state', 'venus_boot'):
            # Replace function tokens, including original run's call to boot_core.
            import re
            original = re.sub(r'\b' + symbol + r'\(', 'before_' + symbol + '(', original)
        originals.append(original)
    body = diag + unchanged + '\n' + '\n'.join(originals) + '\n' + '\n'.join(bodies)
    template = (out / 'native.h').read_text()
    native = template.replace('/* SOURCE_DEFINITIONS */', definitions).replace('/* SOURCE_BODIES */', body)
    native += '\n' + (out / 'checks.h').read_text()
    (out / 'native.c').write_text(native)
    commands, results = [], []

    def run(label, argv, expected_failure=False):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        (out / (label + '.stdout')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        commands.append(dict(label=label, argv=argv, exit_code=result.returncode))
        if expected_failure:
            assert result.returncode == -6 and 'Assertion' in result.stderr, (label, result.returncode, result.stderr)
        else:
            assert result.returncode == 0, (label, result.returncode, result.stderr)
        return result

    def native_run(name, source, config, negative=False):
        path = out / (name + '.c')
        path.write_text(source)
        run(name + '-compile', ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
            '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
            '-DCONFIG_VIDEO_QCOM_IRIS=' + str(config), str(path), '-o', str(out / name)])
        result = run(name, [str(out / name)], negative)
        if not negative:
            assert not result.stderr
            results.append(json.loads(result.stdout))

    native_run('iris-disabled', native, 0)
    native_run('iris-enabled', native, 1)
    controls = {
        'lost-default-off': ('static bool spx_hfi_startup_diag;', 'static bool spx_hfi_startup_diag = true;'),
        'lost-enable-gate': ('!READ_ONCE(spx_hfi_startup_diag) || ', ''),
        'lost-iris1-scope': ('!IS_IRIS1(core) ||', '((void)core, false) ||'),
        'lost-line-cap': ('atomic_read(&spx_hfi_startup_diag_lines) >= 32', 'false'),
        'wrong-poll-return': ('ret = -ETIMEDOUT;', 'ret = -EINVAL;'),
        'wrong-queue-observation': ('&hdev->ifaceq_table.da, hdev->ifaceq_table.size, (u32)SHARED_QSIZE,',
                                    '&hdev->sfr.da, hdev->ifaceq_table.size, (u32)SHARED_QSIZE,'),
    }
    # The cap's two stages are intentionally both removed for this corruption.
    for name, (old, new) in controls.items():
        mutated = body.replace(old, new)
        if name == 'lost-line-cap':
            mutated = mutated.replace('return atomic_inc_return(&spx_hfi_startup_diag_lines) <= 32;',
                                      'return atomic_inc_return(&spx_hfi_startup_diag_lines) > 0;')
        if name == 'wrong-poll-return':
            # Leave the preimage oracle intact.
            mutated = body.replace('\n'.join(bodies), '\n'.join(bodies).replace(old, new))
        assert mutated != body
        native_run(name, native.replace(body, mutated), 0, True)
    run('style', [str(g.REPO / 'scripts/checkpatch.pl'), '--no-tree', '--no-signoff',
                   '--ignore', 'COMMIT_MESSAGE', str(out / 'scoped.diff')])
    assert live(rows, changes) == checked
    assert not g.recovery(a).get('next_entry', '')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), parent_attempt=a['attempt'],
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        parent_source_manifest_sha256=g.sha(source_manifest), compiled_source_paths=checked,
        exact_three_source_changes=changes, insertion_only_scope=True,
        default_off_read_only_iris1=True, shared_line_cap=32,
        native_actual_body_results=results, rejected_candidate_controls=list(controls),
        commands=commands, deployed=False, hardware_operations=0,
        limits=['MMIO, sleeps and firmware/API leaf calls are mocked; actual control bodies are extracted verbatim.',
                'C11 atomic mocks verify the line-cap algorithm, not kernel concurrency on hardware.',
                'Only the diagnostic adds a powered wrapper version read; no poll/control-write/return changes.',
                'No actual auth-reset/remote-state return, DMA address, HFI response or media operation observed.'])
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    manifest = g.files(out)
    (out / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(files=len(manifest), manifest_sha256=g.sha(out / 'sha256.json'),
                         native=results, rejected_controls=len(controls))), flush=True)


if __name__ == '__main__':
    main()
