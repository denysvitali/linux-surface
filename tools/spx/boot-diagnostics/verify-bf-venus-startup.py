#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise BF log interpretation with actual-C captures and the actual BE log."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bf_venus_startup as parser
import bf_startup_review as interpreter
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

MAIN = r'''
int main(void) {
    struct venus_resources res=resources(3);struct device dev={0};
    struct venus_core core={.dev=&dev,.res=&res,.cpu_cs_base=cpu,.wrapper_base=wrapper,.wrapper_tz_base=tz_wrapper,.use_tz=true};
    struct venus_hfi_device hdev={.core=&core,.ifaceq_table={.da=0xabcdef00,.size=2461696},.sfr={.da=0x12345600,.size=4096}};
    reset(true,true);available=true;load_error=boot_error=protect_error=property_error=0;remote_error=-EINVAL;
    ready_after=100;ctrl_result=2;
    assert(!venus_boot(&core));assert(!venus_set_hw_state(&core,true));assert(venus_run(&hdev)==-ETIMEDOUT);
    assert(got.nlogs==4);
    printf("[");
    for(unsigned i=0;i<got.nlogs;i++) {
        if(i) printf(",");
        printf("{\"kind\":%u,\"values\":[",got.logs[i].kind);
        for(unsigned j=0;j<6;j++) {if(j) printf(",");printf("%llu",(unsigned long long)got.logs[i].v[j]);}
        printf("]}");
    }puts("]");return 0;
}
'''


def read(path):
    return json.loads(path.read_text())


def render(rows):
    lines = []
    for i, row in enumerate(rows):
        v = row['values']
        signed = lambda x: x - (1 << 64) if x >= 1 << 63 else x
        if row['kind'] == 4:
            body = f'auth-reset pas={v[0]} ret={signed(v[1])}'
        elif row['kind'] == 3:
            body = f'remote-state resume={v[0]} ret={signed(v[1])}'
        elif row['kind'] == 2:
            body = f'buffers queue=0x{v[0]:016x} queue_size={v[1]} uc_size={v[2]} sfr=0x{v[3]:016x} sfr_size={v[4]} tz={v[5]}'
        else:
            assert row['kind'] == 1
            body = f'poll ret={signed(v[0])} count={v[1]} status={v[2]:#x} mask={v[3]:#x} hw={v[4]:#x}'
        lines.append(f'[{27 + i / 100:.6f}] synthetic kernel: {parser.DEVICE}{parser.PREFIX}{body}')
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    out = p.parse_args().output
    os.umask(0o077)
    a = g.load()
    assert a['state'].startswith('BE terminal;')
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == 'c1cea488-ecf7-403e-9581-127ff365fb1e'
    assert not g.recovery(a).get('next_entry', '')
    parent = g.X / 'offline-venus-startup-diag-20261004'
    assert g.sha(parent / 'sha256.json') == '24ac5c41623b08a93ad64b04896db0f0ba467263e65793af1513abede701a5b1'
    assert g.files(parent) == read(parent / 'sha256.json') | {'sha256.json': g.sha(parent / 'sha256.json')}
    native = parent / 'native-v2/native.c'
    before = native.read_text()
    assert before.count('int main(void) {') == 1
    body = before[:before.index('int main(void) {')] + MAIN
    out.mkdir(mode=0o700)
    for name in ('bf_venus_startup.py', 'bf_startup_review.py', 'verify-bf-venus-startup.py'):
        shutil.copy2(HERE / name, out / name)
    shutil.copy2(parent / 'native-v2/linux-hfi_venus_io.h', out / 'linux-hfi_venus_io.h')
    (out / 'native-fixture.c').write_text(body)
    commands = []
    def run(label, argv):
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        (out / (label + '.stdout')).write_text(r.stdout)
        (out / (label + '.stderr')).write_text(r.stderr)
        commands.append(dict(label=label, argv=argv, exit_code=r.returncode))
        assert r.returncode == 0 and not r.stderr, (label, r.stderr)
        return r.stdout
    run('native-compile', ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-DCONFIG_VIDEO_QCOM_IRIS=0', str(out / 'native-fixture.c'), '-o', str(out / 'native-fixture')])
    rows = json.loads(run('native-run', [str(out / 'native-fixture')]))
    kernel = render(rows)
    (out / 'native-derived-synthetic.log').write_text(kernel)
    decoded = parser.parse(kernel)
    assert decoded['line_count'] == 4 and decoded['auth_reset_api_returns'] == [0]
    assert decoded['remote_state_api_observations'][0]['return_value'] == -22
    assert decoded['remote_state_api_observations'][0]['resume_einval_fallback_applicable']
    assert decoded['poll_observations'][0]['late_nonzero_timeout']
    assert decoded['poll_observations'][0]['count'] == 100 and decoded['poll_observations'][0]['status'] == 2
    assert not decoded['firmware_execution_observed'] and not decoded['hfi_initialization_proved']
    positive = {
        'native-late-nonzero-timeout': kernel,
        'empty-observations': '',
        'auth-rejection': kernel.splitlines()[0].replace('ret=0', 'ret=-13') + '\n',
        'zero-status-timeout': kernel.replace('status=0x2', 'status=0'),
        'first-poll-uc-error': kernel.replace('poll ret=-110 count=100 status=0x2', 'poll ret=-22 count=0 status=0x4'),
        'success-poll': kernel.replace('poll ret=-110 count=100 status=0x2', 'poll ret=0 count=1 status=0x1'),
        'unknown-api-errno': kernel.replace('remote-state resume=1 ret=-22', 'remote-state resume=0 ret=-2147483648'),
        'positive-api-result': kernel.replace('auth-reset pas=9 ret=0', 'auth-reset pas=9 ret=2147483647'),
        'dma-outside-mask-observed': kernel.replace('0x00000000abcdef00', '0x00000000df000000'),
        'zero-sfr': kernel.replace('0x0000000012345600', '0x0000000000000000'),
        'shared-cap': kernel * 8,
        'cap-ending-between-stages': (kernel * 7) + '\n'.join(kernel.splitlines()[:3]) + '\n' + kernel.splitlines()[0] + '\n',
    }
    accepted = {}
    for name, text in positive.items():
        accepted[name] = parser.parse(text)
        (out / (name + '.log')).write_text(text)
    assert not accepted['dma-outside-mask-observed']['buffer_observations'][0]['queue_dma_within_declared_mask']
    bad = {
        'wrong-device': kernel.replace('aa00000.video-codec', 'bb00000.video-codec'),
        'unknown-shape': kernel.replace('auth-reset', 'auth-finish'),
        'wrong-pas': kernel.replace('pas=9', 'pas=8'),
        'bad-resume': kernel.replace('resume=1', 'resume=2'),
        'bad-uc-size': kernel.replace('uc_size=3145728', 'uc_size=16777216'),
        'bad-tz': kernel.replace('tz=1', 'tz=3'),
        'return-after-timeout': kernel.replace('poll ret=-110', 'poll ret=0'),
        'count-exceeded': kernel.replace('count=100', 'count=101'),
        'unmasked-iris1-irq': kernel.replace('mask=0x1e2', 'mask=0x1f6'),
        'false-zero-success': kernel.replace('poll ret=-110 count=100 status=0x2', 'poll ret=0 count=1 status=0'),
        'late-error-status': kernel.replace('status=0x2', 'status=0x4'),
        'oversized-dma': kernel.replace('0x00000000abcdef00', '0x100000000abcdef00'),
        'oversized-return': kernel.replace('auth-reset pas=9 ret=0', 'auth-reset pas=9 ret=2147483648'),
        'shared-cap-exceeded': kernel * 8 + kernel.splitlines()[0] + '\n',
        'truncated-record': kernel.replace(' hw=0x30210001', ''),
    }
    rejected = []
    for name, text in bad.items():
        (out / (name + '.log')).write_text(text)
        try:
            parser.parse(text)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('Accepted corruption: ' + name)
    actual_be = (g.X / 'video-startup/kernel.stdout').read_text()
    actual_result = parser.parse(actual_be)
    assert actual_result['line_count'] == 0 and not actual_result['auth_reset_api_observed']
    (out / 'actual-be-parser-replay.json').write_text(json.dumps(actual_result, indent=2) + '\n')
    pas_spec = importlib.util.spec_from_file_location('be_pas', g.X / 'build/pas-area-log-review/parse_log.py')
    pas = importlib.util.module_from_spec(pas_spec)
    sys.path.insert(0, str(g.X / 'build/pas-area-log-review'))
    pas_spec.loader.exec_module(pas)
    startup = read(g.X / 'video-startup/result.json')
    startup.update(attempt='20261004bf', release='7.3.0-rc2-spx-mainline-20261004bf+',
        venus_startup_parameter=dict(observed=True, value='Y', mode='0o400'))
    modeled = interpreter.analyze(startup, actual_be + kernel, pas.parse(actual_be))
    assert modeled['venus_startup']['poll_observations'][0]['late_nonzero_timeout']
    assert modeled['pas_memory_setup_zero_observed'] and modeled['probe_errnos'] == [-110]
    missing = startup | {'venus_startup_parameter': dict(observed=False, error='synthetic missing module')}
    no_parameter = interpreter.analyze(missing, actual_be, pas.parse(actual_be))
    assert not no_parameter['venus_startup']['auth_reset_api_observed']
    rejected_parameters = []
    for witness in [dict(observed=True, value='N', mode='0o400'), dict(observed=True, value='Y', mode='0o600'),
                    dict(observed=False, error='missing')]:
        try:
            interpreter.analyze(startup | {'venus_startup_parameter': witness}, actual_be + kernel, pas.parse(actual_be))
        except AssertionError:
            rejected_parameters.append(witness)
        else:
            raise AssertionError('Accepted invalid parameter witness')
    report = dict(utc=datetime.now(timezone.utc).isoformat(), native_actual_body_records=4,
        native_parent_manifest_sha256=g.sha(parent / 'sha256.json'), positive_traces=list(accepted),
        rejected_corruptions=rejected, actual_be_log_sha256=g.sha(g.X / 'video-startup/kernel.stdout'),
        actual_be_replayed_with_zero_new_observations=True, interpreter_positive_cases=2,
        rejected_parameter_witnesses=rejected_parameters, modeled_interpreter_explicitly_synthetic=True,
        commands=commands, hardware_operations=0, deployed=False, hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    print(json.dumps(dict(manifest_sha256=g.sha(out / 'sha256.json'), report=report)), flush=True)


if __name__ == '__main__':
    main()
