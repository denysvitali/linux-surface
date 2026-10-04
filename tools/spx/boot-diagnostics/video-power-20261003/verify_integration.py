#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check Iris1 DT resources, binding mutations and actual HFI/resume C bodies."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import sys

import libfdt
from video_dt_contract import validate as validate_provider_contracts

sys.dont_write_bytecode = True
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
TOOLS = Path('/var/tmp/spx-dtschema-venv-20260915/bin')
NODE = '/soc@0/video-codec@aa00000'
MEM = '/reserved-memory/video-firmware'


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--dtb', type=Path)
    args = p.parse_args()
    root = args.output
    root.mkdir(mode=0o700)
    commands = []

    def run(name, argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=90)
        (root / (name + '.stdout')).write_text(result.stdout)
        (root / (name + '.stderr')).write_text(result.stderr)
        commands.append(dict(name=name, argv=argv, exit_code=result.returncode))
        assert result.returncode == 0, (name, result.stdout, result.stderr)
        return result.stdout + result.stderr

    schema = root / 'schema'
    shutil.copytree('/var/tmp/spx-camera-offline-20260922/schema-subset', schema)
    for name in ('qcom,venus-common.yaml', 'qcom,sc8180x-venus.yaml'):
        target = schema / 'media' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / 'Documentation/devicetree/bindings/media' / name, target)
    assert not run('binding-doc', [str(TOOLS / 'dt-doc-validate'),
                                   str(schema / 'media/qcom,sc8180x-venus.yaml')]).strip()
    if args.dtb:
        shutil.copy2(args.dtb, root / 'board.dtb')
    else:
        run('cpp', ['gcc', '-E', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
                     '-I', str(REPO / 'include'), '-I', str(REPO / 'scripts/dtc/include-prefixes'),
                     '-I', str(REPO / 'arch/arm64/boot/dts/qcom'),
                     str(REPO / 'arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dts'),
                     '-o', str(root / 'board.pre.dts')])
        run('dtc', ['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(root / 'board.dtb'),
                     str(root / 'board.pre.dts')])
    raw = (root / 'board.dtb').read_bytes()
    provider_contracts = validate_provider_contracts(raw)
    (root / 'provider-contracts.json').write_text(json.dumps(provider_contracts, indent=2) + '\n')
    fdt = libfdt.Fdt(raw)
    off = fdt.path_offset(NODE)

    def cells(offset, prop):
        value = bytes(fdt.getprop(offset, prop))
        return list(struct.unpack('>' + 'I' * (len(value) // 4), value))

    def strings(offset, prop):
        return bytes(fdt.getprop(offset, prop)).rstrip(b'\0').decode().split('\0')

    providers = {}
    for path in ('/soc@0/clock-controller@ab00000', '/soc@0/clock-controller@100000',
                 '/soc@0/system-cache-controller@9200000', '/soc@0/iommu@15000000',
                 '/soc@0/interconnect@1740000', '/interconnect-mc-virt',
                 '/soc@0/interconnect@9680000', '/soc@0/interconnect@1500000'):
        try:
            providers[path] = cells(fdt.path_offset(path), 'phandle')[0]
        except libfdt.FdtException:
            pass
    video = providers['/soc@0/clock-controller@ab00000']
    gcc = providers['/soc@0/clock-controller@100000']
    assert cells(off, 'reg') == [0, 0xaa00000, 0, 0x100000]
    assert cells(off, 'interrupts') == [0, 174, 4]
    assert strings(off, 'compatible') == ['qcom,sc8180x-venus']
    assert strings(off, 'status') == ['okay']
    assert strings(off, 'clock-names') == ['core', 'iface', 'bus', 'vcodec0_core',
                                          'vcodec0_bus', 'vcodec1_core', 'vcodec1_bus']
    assert cells(off, 'clocks') == [video, 4, video, 0, gcc, 227, video, 2,
                                   gcc, 225, video, 3, gcc, 226]
    assert cells(off, 'resets') == [gcc, 41, video, 0]
    assert strings(off, 'reset-names') == ['bus', 'core']
    assert strings(off, 'power-domain-names') == ['venus', 'vcodec0', 'vcodec1', 'mmcx']
    domains = cells(off, 'power-domains')
    assert domains[:6] == [video, 0, video, 1, video, 2]
    assert fdt.get_name(fdt.node_offset_by_phandle(domains[6])) == 'power-controller'
    # SC8180X_MMCX is checked against the source header, rather than inferred.
    import re
    header = (REPO / 'include/dt-bindings/power/qcom,rpmhpd.h').read_text()
    assert domains[7] == int(re.search(r'#define SC8180X_MMCX\s+(\d+)', header)[1])
    smmu = providers['/soc@0/iommu@15000000']
    assert cells(off, 'iommus') == [smmu, 0x2300, 0x60]
    assert cells(off, 'interconnects') == [providers['/soc@0/interconnect@1740000'], 7, 0,
        providers['/interconnect-mc-virt'], 1, 0, providers['/soc@0/interconnect@9680000'], 0, 0,
        providers['/soc@0/interconnect@1500000'], 54, 0]
    contract_controls = []
    correct = cells(off, 'interconnects')
    for name, values in [
            ('original-missing-all-tags', [v for i, v in enumerate(correct) if i % 3 != 2]),
            ('missing-first-tag', correct[:2] + correct[3:]),
            ('truncated-last-tag', correct[:-1]),
            ('extra-argument', correct + [0]),
            ('wrong-provider', [1] + correct[1:]),
            ('wrong-endpoint', [correct[0], 8] + correct[2:]),
            ('changed-tag', correct[:2] + [1] + correct[3:])]:
        changed = libfdt.Fdt(raw)
        changed.resize(len(raw) + 4096)
        changed.setprop(changed.path_offset(NODE), 'interconnects',
                        struct.pack('>' + 'I' * len(values), *values))
        data = bytes(changed.as_bytearray())
        (root / (name + '.dtb')).write_bytes(data)
        try:
            validate_provider_contracts(data)
        except ValueError as error:
            contract_controls.append(dict(name=name, rejected=True, error=str(error)))
        else:
            raise AssertionError(f'Malformed interconnect accepted: {name}')
    (root / 'provider-contract-controls.json').write_text(
        json.dumps(contract_controls, indent=2) + '\n')
    mem = fdt.path_offset(MEM)
    assert cells(off, 'memory-region') == cells(mem, 'phandle')
    assert cells(mem, 'size') == [0, 0x500000]
    assert cells(mem, 'alignment') == [0, 0x100000]
    assert cells(mem, 'alloc-ranges') == [0, 0x80000000, 0, 0x80000000]
    assert bytes(fdt.getprop(mem, 'no-map')) == b''
    try:
        fdt.getprop(mem, 'reg')
    except libfdt.FdtException as error:
        assert error.err == -libfdt.NOTFOUND
    else:
        raise AssertionError('firmware memory must be dynamically allocated')
    assert strings(off, 'firmware-name') == ['qcom/msft/surface/pro-x-sq2/qcvss8180.mbn']
    opps = {}
    table = fdt.path_offset(NODE + '/opp-table')
    assert cells(off, 'operating-points-v2') == cells(table, 'phandle')
    child = fdt.first_subnode(table)
    while True:
        hz = struct.unpack('>Q', bytes(fdt.getprop(child, 'opp-hz')))[0]
        required = fdt.node_offset_by_phandle(cells(child, 'required-opps')[0])
        opps[hz] = cells(required, 'opp-level')[0]
        try:
            child = fdt.next_subnode(child)
        except libfdt.FdtException as error:
            assert error.err == -libfdt.NOTFOUND
            break
    assert opps == {200000000: 64, 240000000: 64, 338000000: 128,
                    365000000: 192, 444000000: 256, 533000000: 384}

    def validate(name, path):
        return run(name, [str(TOOLS / 'dt-validate'), '-s', str(schema),
                          '-l', 'qcom,sc8180x-venus', str(path)])

    output = validate('binding-enabled', root / 'board.dtb')
    assert NODE.split('/')[-1] not in output, output
    negative = []
    for name, prop, value in [('bad-clock-name', 'clock-names', b'wrong\0' * 7),
                              ('missing-reset', 'resets', None),
                              ('two-iommus', 'iommus', struct.pack('>6I', smmu, 0x2300, 0x60,
                                                                  smmu, 0x2301, 4)),
                              ('missing-opp', 'operating-points-v2', None)]:
        changed = libfdt.Fdt(raw)
        changed.resize(len(raw) + 4096)
        node = changed.path_offset(NODE)
        if value is None:
            changed.delprop(node, prop)
        else:
            changed.setprop(node, prop, value)
        path = root / (name + '.dtb')
        path.write_bytes(changed.as_bytearray())
        output = validate(name, path)
        assert 'video-codec@aa00000' in output and prop in output, output
        negative.append(name)
    # Unused generic SoC description stays disabled.
    assert 'status = "disabled";' in block((REPO / 'arch/arm64/boot/dts/qcom/sc8180x.dtsi').read_text(),
                                           'venus: video-codec@aa00000')

    core = (REPO / 'drivers/media/platform/qcom/venus/core.c').read_text()
    hfi = (REPO / 'drivers/media/platform/qcom/venus/hfi_venus.c').read_text()
    cmds = (REPO / 'drivers/media/platform/qcom/venus/hfi_cmds.c').read_text()
    source = PREAMBLE + '\n' + block(cmds, 'void pkt_sys_init(') + '\n'
    source += block(hfi, 'static int venus_core_init(') + '\n'
    source += block(core, 'static __maybe_unused int venus_runtime_resume(') + '\n'
    firmware = (REPO / 'drivers/media/platform/qcom/venus/firmware.c').read_text()
    source += block(firmware, 'int venus_boot(') + '\n' + TESTS
    (root / 'native.c').write_text(source)
    run('native-build', ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                         '-Wno-unused-parameter', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                         str(root / 'native.c'), '-o', str(root / 'native')])
    output = run('native-run', [str(root / 'native')])
    counts = json.loads(output)
    assert counts == {'resume_cases': 10, 'sys_init_cases': 12, 'firmware_cases': 16}, counts
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    changed_sources = {
        'lost-sys-init-policy': source.replace('core->res->hfi_video_arch ?: HFI_VIDEO_ARCH_OX',
                                             'HFI_VIDEO_ARCH_OX'),
        'lost-resume-unwind': source.replace('pm_ops->core_power(core, POWER_OFF);',
                                            '(void)core;'),
        'lost-firmware-errno': source.replace('dev_err(dev, "failed to load video firmware %s (%d)\\n", fwpath, ret);\n\t\treturn ret;',
                                            'dev_err(dev, "failed to load video firmware %s (%d)\\n", fwpath, ret);\n\t\treturn -EINVAL;'),
    }
    for name, changed in changed_sources.items():
        assert changed != source, name
        path = root / (name + '.c')
        path.write_text(changed)
        run(name + '-build', ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                              '-Wno-unused-parameter', '-fsanitize=address,undefined',
                              '-fno-omit-frame-pointer', str(path), '-o', str(root / name)])
        result = subprocess.run([str(root / name)], capture_output=True, text=True, timeout=10)
        (root / (name + '.stdout')).write_text(result.stdout)
        (root / (name + '.stderr')).write_text(result.stderr)
        assert result.returncode == -6 and 'Assertion' in result.stderr, (name, result.returncode, result.stderr)
    # Probe errors after successful power-up must quiesce IRQ before power-off.
    cleanup = core[core.index('err_runtime_disable:'):core.index('err_hfi_destroy:', core.index('err_runtime_disable:'))]
    assert cleanup.index('disable_irq(core->irq)') < cleanup.index('POWER_OFF')
    assert 'IS_IRIS1(core) && powered' in cleanup
    assert 'return ret;' in block((REPO / 'drivers/media/platform/qcom/venus/firmware.c').read_text(),
                                  'int venus_boot(')
    shutil.copy2(Path(__file__), root / 'verify_integration.py')
    shutil.copy2(Path(__file__).with_name('video_dt_contract.py'), root / 'video_dt_contract.py')
    (root / 'result.json').write_text(json.dumps(dict(dt_resource_checks=True, opps=opps,
        provider_argument_counts_and_paths_verified=True,
        provider_contract_negative_controls=contract_controls,
        dynamic_firmware_reservation=True, binding_negative_controls=negative, native=counts,
        native_negative_controls=list(changed_sources),
        commands=commands, hardware_operations=0, deployed=False,
        limits=['Leaf ICC/PM/HFI calls are mocked; no SCM/PAS authentication, physical allocation,',
                'watchdog routing, power sequencing, firmware response or media acceptance is proved.']), indent=2) + '\n')
    manifest = {str(path.relative_to(root)): sha(path) for path in sorted(root.rglob('*')) if path.is_file()}
    (root / 'sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(files=len(manifest), manifest_sha256=sha(root / 'sha256.json'), native=counts)))


PREAMBLE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t phys_addr_t;
#define __maybe_unused
#define EPROBE_DEFER 517
#define CONFIG_QCOM_MDT_LOADER 1
#define IS_ENABLED(x) (x)
#define VENUS_PAS_ID 9
#define HFI_VIDEO_ARCH_OX 1
#define HFI_CMD_SYS_INIT 0x10001
#define VENUS_STATE_INIT 1
#define POWER_ON 1
#define POWER_OFF 0
#define IS_IRIS1(core) ((core)->res->vpu_version == 1)
#define kbps_to_icc(x) (x)
#define dev_warn(dev, ...) ((void)(dev))
#define dev_err(dev, ...) ((void)(dev))
struct device { void *core, *of_node; };
struct venus_resources { u32 hfi_video_arch; unsigned vpu_version;
    const char *fwname; u32 cp_start, cp_size, cp_nonpixel_start, cp_nonpixel_size; };
struct venus_core;
struct venus_pm_ops { int (*core_power)(struct venus_core *, int); };
struct venus_hfi_device { unsigned state; };
struct venus_core { struct device *dev; struct venus_resources *res;
    const struct venus_pm_ops *pm_ops; void *video_path, *cpucfg_path; struct venus_hfi_device hdev;
    bool use_tz; struct { size_t mem_size; phys_addr_t mem_phys; } fw; };
struct hfi_pkt_hdr { u32 size, pkt_type; };
struct hfi_sys_init_pkt { struct hfi_pkt_hdr hdr; u32 arch_type; };
struct hfi_sys_get_property_pkt { unsigned ignored; };
static unsigned failure, sequence, powered, resumed, defaults, writes;
static u32 video_bw, cfg_bw;
static struct hfi_sys_init_pkt sent;
static bool available = true;
static int load_error, boot_error, protect_error;
static unsigned load_calls, boot_calls, shutdown_calls;
static bool qcom_pas_is_available(void) { return available; }
static int of_property_read_string_index(void *node, const char *prop, unsigned index,
                                         const char **value) { *value = "board-fw"; return 0; }
static int venus_load_fw(struct venus_core *core, const char *path, phys_addr_t *phys,
                         size_t *size) {
    assert(!strcmp(path, "board-fw")); load_calls++;
    *phys = 0xbf000000; *size = 0x500000; return load_error;
}
static int qcom_pas_auth_and_reset(unsigned id) { assert(id == 9); boot_calls++; return boot_error; }
static int venus_boot_no_tz(struct venus_core *core, phys_addr_t phys, size_t size) {
    assert(phys == 0xbf000000 && size == 0x500000); boot_calls++; return boot_error;
}
static int qcom_scm_mem_protect_video_var(u32 start, u32 size, u32 nonpixel, u32 nonpixel_size) {
    return protect_error;
}
static int qcom_pas_shutdown(unsigned id) { assert(id == 9); shutdown_calls++; return 0; }
static struct venus_hfi_device *to_hfi_priv(struct venus_core *core) { return &core->hdev; }
static void *dev_get_drvdata(struct device *dev) { return dev->core; }
static int icc_set_bw(void *path, u32 avg, u32 peak) {
    if (avg && ++sequence == failure) return -EIO;
    if (path == (void *)1) video_bw = avg; else cfg_bw = avg;
    return 0;
}
static int power(struct venus_core *core, int on) {
    if (on && ++sequence == failure) return -EIO;
    powered = on; return 0;
}
static int hfi_core_resume(struct venus_core *core, bool init) {
    if (++sequence == failure) return -ETIMEDOUT;
    resumed++; return 0;
}
static void venus_set_state(struct venus_hfi_device *hdev, unsigned state) { hdev->state = state; }
static int venus_iface_cmdq_write(struct venus_hfi_device *hdev, void *pkt, bool sync) {
    writes++;
    if (writes == 1) memcpy(&sent, pkt, sizeof(sent));
    if (++sequence == failure) return -EIO;
    return 0;
}
static void pkt_sys_image_version(struct hfi_sys_get_property_pkt *pkt) { pkt->ignored = 0; }
static int venus_sys_set_default_properties(struct venus_hfi_device *hdev) {
    defaults++;
    if (++sequence == failure) return -EINVAL;
    return 0;
}
'''

TESTS = r'''
int main(void) {
    struct venus_resources res = {0};
    struct device dev = {0};
    const struct venus_pm_ops ops = {power};
    struct venus_core core = {.dev=&dev, .res=&res, .pm_ops=&ops,
                              .video_path=(void *)1, .cpucfg_path=(void *)2};
    dev.core = &core;
    unsigned cases = 0;
    for (res.vpu_version=0; res.vpu_version<2; res.vpu_version++) {
        for (failure=0; failure<=4; failure++) {
            sequence=powered=resumed=video_bw=cfg_bw=0;
            int ret = venus_runtime_resume(&dev);
            assert(ret == (failure == 4 ? -ETIMEDOUT : failure ? -EIO : 0));
            if (!failure) {
                assert(powered && resumed == 1 && cfg_bw == 1000);
                assert(video_bw == (res.vpu_version ? 200000U : 20000U));
            } else if (res.vpu_version) {
                assert(!powered && !video_bw && !cfg_bw && !resumed);
            } else {
                assert(video_bw == (failure == 1 ? 0U : 20000U));
                assert(cfg_bw == (failure <= 2 ? 0U : 1000U));
                assert(powered == (failure == 4));
            }
            cases++;
        }
    }
    assert(cases == 10);
    for (res.hfi_video_arch=0; res.hfi_video_arch<=2; res.hfi_video_arch++) {
        for (failure=0; failure<=3; failure++) {
            sequence=defaults=writes=0; memset(&sent,0,sizeof(sent));
            int ret = venus_core_init(&core);
            assert(sent.hdr.size == 12 && sent.hdr.pkt_type == 0x10001);
            assert(sent.arch_type == (res.hfi_video_arch ? res.hfi_video_arch : 1));
            assert(ret == (failure == 1 ? -EIO : failure == 3 ? -EINVAL : 0));
            assert(defaults == (failure == 1 ? 0U : 1U));
            assert(writes == (failure == 1 ? 1U : 2U));
        }
    }
    for (unsigned tz=0; tz<2; tz++) {
        core.use_tz = tz;
        for (unsigned scenario=0; scenario<8; scenario++) {
            available = scenario != 6;
            load_error = scenario == 1 ? -ENOENT : scenario == 2 ? -EIO :
                         scenario == 3 ? -EPROBE_DEFER : 0;
            boot_error = scenario == 4 ? -EACCES : scenario == 5 ? -ETIMEDOUT : 0;
            protect_error = scenario == 7 ? -EINVAL : 0;
            res.cp_size = scenario == 7 ? 0x1000000 : 0;
            load_calls=boot_calls=shutdown_calls=0;
            int ret = venus_boot(&core);
            int expected = load_error ? load_error : boot_error ? boot_error :
                           tz && scenario == 6 ? -EPROBE_DEFER :
                           tz && scenario == 7 ? -EINVAL : 0;
            assert(ret == expected);
            assert(load_calls == (tz && scenario == 6 ? 0U : 1U));
            assert(boot_calls == (load_error || (tz && scenario == 6) ? 0U : 1U));
            assert(shutdown_calls == (tz && scenario == 7 ? 1U : 0U));
            if (boot_calls) assert(core.fw.mem_phys == 0xbf000000 && core.fw.mem_size == 0x500000);
        }
    }
    puts("{\"resume_cases\":10,\"sys_init_cases\":12,\"firmware_cases\":16}");
    return 0;
}
'''


if __name__ == '__main__':
    main()
