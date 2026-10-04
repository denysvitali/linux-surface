#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Correlate BE's actual reset boundary with exact source and retained UC bytes."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import libfdt
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import be_boot_guard as g

HERE = Path(__file__).resolve().parent
VENDOR = Path('/var/lib/spx-boot-diagnostics/attempts/20261003ax/offline-video-iris1-20261003/contracts')
VENDOR_SHA = '3bb3dfcd86755512b811bda2e955bce5083c2e42c2e93ffc53f550629f8eee21'
PINS = {
    0x356df4: ('mov', 'w11, #0x1000000'),
    0x356df8: ('ldp', 'w8, w9, [x8, #0x24]'),
    0x356dfc: ('add', 'w10, w9, w8'),
    0x356e04: ('sub', 'w11, w10, w11'),
    0x356e0c: ('str', 'w11, [x9, #0x64]'),
    0x356f34: ('mov', 'w10, #0x1000000'),
    0x356f3c: ('str', 'w10, [x9, #0x68]'),
    0x357084: ('mov', 'w10, #1'),
    0x35708c: ('str', 'w10, [x9, #0x48]'),
    0x3571bc: ('ldr', 'w24, [x9, #0x4c]'),
}


def read(path):
    return json.loads(path.read_text())


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sealed(path, digest=None):
    actual = g.sha(path / 'sha256.json')
    assert digest is None or actual == digest
    assert g.files(path) == read(path / 'sha256.json') | {'sha256.json': actual}
    return actual


CHECKS = r'''
int main(void) {
    const u32 values[]={0,1,2,4,5,6,0xfe,0xffffffff};
    struct venus_resources res={VPU_VERSION_IRIS1,HFI_VERSION_4XX};
    struct device dev={0};
    struct venus_core core={&dev,&res,cpu,wrapper,NULL};
    struct venus_hfi_device hdev={&core,0};core.priv=&hdev;
    assert(to_hfi_priv(&core)==&hdev);
    unsigned cases=0, late_nonzero_timeouts=0;
    for(unsigned v=0;v<8;v++) for(unsigned after=1;after<=101;after++) {
        memset(cpu,0,sizeof(cpu));memset(wrapper,0,sizeof(wrapper));
        memset(&got,0,sizeof(got));polls=0;ready_after=after;ctrl_result=values[v];
        wrapper[0x10/4]=0x1f6;
        int actual=venus_boot_core(&hdev);
        int expected=-ETIMEDOUT;
        if(values[v] && after<=100) {
            if((values[v]&0xfe)==4) expected=-EINVAL;
            else if(after<100) expected=0;
        }
        assert(actual==expected);
        unsigned expected_reads=(!values[v] || after>100)?100:after;
        assert(polls==expected_reads);
        assert(got.len==expected_reads+3);
        assert(got.trace[1].op==1 && got.trace[1].offset==0xe0010 && got.trace[1].value==0x1e2);
        assert(got.trace[2].op==1 && got.trace[2].offset==0xd2048 && got.trace[2].value==1);
        for(unsigned i=3;i<got.len;i++) assert(got.trace[i].op==0 && got.trace[i].offset==0xd204c);
        if(after==100 && values[v] && (values[v]&0xfe)!=4) {
            assert(actual==-ETIMEDOUT && got.trace[got.len-1].value==values[v]);
            late_nonzero_timeouts++;
        }
        cases++;
    }
    printf("{\"cases\":%u,\"late_nonzero_timeouts\":%u,\"config_iris\":%u}\n",
        cases,late_nonzero_timeouts,CONFIG_VIDEO_QCOM_IRIS);
}
'''


def main():
    os.umask(0o077)
    a = g.load()
    boot = g.trial_identity(a)
    assert boot == '11e69e59-c493-498a-9dde-d056f13ccc18'
    report = read(g.X / 'startup-review/report.json')
    assert report['boot_id'] == boot and report['probe_errnos'] == [-110]
    assert report['pas_init_returns'] == report['pas_memory_returns'] == [0]
    sealed(g.X / 'startup-review', '6c3d1d727bf6c983a17d0787c28dae99b36f23d172dd2fc396219d07e49f3754')
    sealed(g.X / 'actual-media-boundary', 'fef05b30c821c78dd8acf9d4970bb9d36ace0176266922330cf2fb0b56a12641')
    sealed(VENDOR, VENDOR_SHA)
    out = g.X / 'offline-core-reset-v2'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    rows = read(g.X / 'dtb-build/candidate-source-files.json')
    base = 'drivers/media/platform/qcom/venus/'
    sources = {}
    for name in ('core.c', 'core.h', 'hfi.c', 'hfi_venus.c', 'hfi_venus_io.h', 'hfi_helper.h', 'firmware.c', 'pm_helpers.c'):
        path = g.REPO / base / name
        assert g.sha(path) == rows[base + name]['sha256']
        shutil.copy2(path, out / ('linux-' + name))
        sources[name] = path.read_text()
    verify = module(HERE / 'video-iris1-20261003/verify_interrupts.py', 'actual_boot_body')
    block = verify.block
    bodies = {
        'probe': block(sources['core.c'], 'static int venus_probe('),
        'boot': block(sources['firmware.c'], 'int venus_boot('),
        'init': block(sources['firmware.c'], 'int venus_firmware_init('),
        'resume': block(sources['hfi_venus.c'], 'static int venus_resume('),
        'power_on': block(sources['hfi_venus.c'], 'static int venus_power_on('),
        'run': block(sources['hfi_venus.c'], 'static int venus_run('),
        'boot_core': block(sources['hfi_venus.c'], 'static int venus_boot_core('),
        'hw_version': block(sources['hfi_venus.c'], 'static u32 venus_hwversion('),
    }
    assert bodies['probe'].index('ret = venus_boot(core);') < bodies['probe'].index('ret = hfi_core_resume(core, true);') < bodies['probe'].index('ret = hfi_core_init(core);')
    assert 'ret = qcom_pas_auth_and_reset(VENUS_PAS_ID);' in bodies['boot']
    assert 'failed to boot video firmware' in bodies['boot']
    assert 'core->use_tz = true;' in bodies['init']
    tree = libfdt.Fdt((g.X / 'video-startup/actual-fdt.dtb').read_bytes())
    tree.path_offset('/soc@0/video-codec@aa00000')
    try:
        tree.path_offset('/soc@0/video-codec@aa00000/video-firmware')
    except libfdt.FdtException as error:
        assert error.err == -libfdt.NOTFOUND
    else:
        raise AssertionError('Actual DT enables the non-TZ child')
    assert bodies['run'].index('ret = venus_boot_core(hdev);') < bodies['run'].index('venus_hwversion(hdev);')
    assert 'writel(hdev->ifaceq_table.da, cpu_cs_base + UC_REGION_ADDR);' in bodies['run']
    assert 'writel(SHARED_QSIZE, cpu_cs_base + UC_REGION_SIZE);' in bodies['run']
    assert 'count >= max_tries' in bodies['boot_core'] and 'max_tries = 100' in bodies['boot_core']
    for name, body in bodies.items():
        (out / (name + '.c-fragment')).write_text(body + '\n')
    shutil.copy2(HERE / 'video-iris1-20261003/verify_interrupts.py', out / 'native-scaffold.py')
    defs = block(sources['core.h'], 'enum vpu_version {') + '\n' + block(sources['hfi_helper.h'], 'enum hfi_version {')
    core = sources['core.h']
    defs += '\n' + core[core.index('#define IS_V1(core)'):core.index('static inline bool is_lite(')]
    native = verify.PREAMBLE + defs + verify.SCAFFOLD + bodies['boot_core'] + CHECKS
    results = []
    for config in (0, 1):
        path = out / f'poll-boundary-{config}.c'
        path.write_text(native)
        argv = ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
            f'-DCONFIG_VIDEO_QCOM_IRIS={config}', str(path), '-o', str(path.with_suffix(''))]
        compiled = subprocess.run(argv, capture_output=True, timeout=30)
        (out / f'compile-{config}.stdout').write_bytes(compiled.stdout)
        (out / f'compile-{config}.stderr').write_bytes(compiled.stderr)
        assert compiled.returncode == 0, compiled.stderr.decode()
        tested = subprocess.run([str(path.with_suffix(''))], capture_output=True, timeout=30)
        (out / f'native-{config}.stdout').write_bytes(tested.stdout)
        (out / f'native-{config}.stderr').write_bytes(tested.stderr)
        assert tested.returncode == 0 and not tested.stderr, tested.stderr.decode()
        data = json.loads(tested.stdout)
        assert data['cases'] == 808 and data['late_nonzero_timeouts'] == 5
        results.append(data | dict(compile_argv=argv))
    # Re-decode the sealed device contracts; never execute vendor instructions.
    audit = module(VENDOR / 'audit_contracts.py', 'retained_iris_contract')
    loader = module(VENDOR / 'audit_pep_loader.py', 'retained_image')
    image = loader.Image((VENDOR / 'oem-00040.sys').read_bytes())
    ranges, tables, listing = audit.contracts(image)
    prior = read(VENDOR / 'contracts.json')
    assert ranges == prior['ranges'] and tables == prior['retained_tables']
    decoded = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    pinned = []
    for address, expected in PINS.items():
        insn, = list(decoded.disasm(image.read(address, 4), image.base + address))
        assert (insn.mnemonic, insn.op_str) == expected, hex(address)
        pinned.append(dict(rva=hex(address), mnemonic=insn.mnemonic, operands=insn.op_str))
    assert prior['table_uc_iova'] == 0xdf000000 and prior['uc_window_size'] == 0x1000000
    for name in ('contracts.json', 'sha256.json', 'audit_contracts.py', 'audit_pep_loader.py', 'oem-00040.sys', 'disassembly.txt'):
        shutil.copy2(VENDOR / name, out / ('retained-' + name))
    selected = [line for line in (VENDOR / 'disassembly.txt').read_text().splitlines()
        if re.match(r'^0x[0-9a-f]+:', line) and 0x356dd8 <= int(line.split(':')[0], 16) < 0x357300]
    (out / 'vendor-reset-selected.txt').write_text('\n'.join(selected) + '\n')
    result = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=boot,
        actual_startup_manifest_sha256=report['startup']['manifest_sha256'],
        actual_startup_review_manifest_sha256=g.sha(g.X / 'startup-review/sha256.json'),
        pas_initialization_and_memory_setup_observed_zero=True,
        auth_reset_zero_inferred_from_exact_probe_order=True,
        auth_reset_raw_smc_observed=False, actual_last_control_value_observed=False,
        failure_stage='venus_resume -> venus_power_on -> venus_run -> venus_boot_core',
        failure_errno=-110, source_function_bodies_exact=True,
        timeout_poll_budget=100, native_cases=results,
        last_poll_can_be_nonzero_and_still_return_timeout=True,
        hardware_version_read_is_after_failed_boot=True, live_hardware_version_observed=False,
        retained_contract_pins_redecoded=len(audit.PINS), additional_reset_pins=pinned,
        retained_uc_iova='0xdf000000', retained_uc_window_bytes=0x1000000,
        linux_uc_base_policy='DMA queue-table address', linux_uc_size_policy='SHARED_QSIZE (3MiB)',
        actual_linux_queue_iova_observed=False, linux_dma_limit='0xbfffffff',
        root_cause_proven=False, compiled_sources_changed=False,
        hardware_operations=0, media_acceptance_passed=False, hardware_acceptance_closed=False,
        next_observations=['actual queue/SFR DMA addresses and lengths',
            'existing control poll count and final value', 'wrapper hardware version',
            'auth-reset and remote-state return values'],
        limits=['Static vendor data is not Windows runtime or a proved Linux UC requirement.',
            'Zero API returns and source inference do not prove firmware/HFI/media operation.',
            'No live MMIO read, component rebind, firmware reload or source change is performed.'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(g.files(out), indent=2) + '\n')
    sealed(out)
    assert g.trial_identity(a) == boot
    os.sync()
    print(json.dumps(result | dict(manifest_sha256=g.sha(out / 'sha256.json')), indent=2))


if __name__ == '__main__':
    main()
