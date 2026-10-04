#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare actual pre-BA/candidate PAS and SCM bodies with mocked leaf operations."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
REPO = Path('/home/dvitali/Documents/git/linux-surface-next')
BEFORE = Path('/var/tmp/spx-pas-diag-20261004')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def macro(source, name):
    lines = source.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.match(r'#define\s+' + re.escape(name) + r'\b', line):
            stop = index + 1
            while lines[stop - 1].rstrip().endswith('\\'):
                stop += 1
            return ''.join(lines[index:stop])
    raise ValueError(name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    out = p.parse_args().output
    os.umask(0o077)
    out.mkdir(mode=0o700)
    helper = REPO / 'tools/spx/boot-diagnostics/video-power-20261003/verify_power.py'
    spec = importlib.util.spec_from_file_location('actual_c_body', helper)
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    shutil.copy2(helper, out / 'extract_body.py')
    sources = {}
    for name in ('qcom_scm.c', 'qcom_scm-smc.c', 'qcom_scm.h'):
        path = REPO / 'drivers/firmware/qcom' / name
        sources[name] = path.read_text()
        shutil.copy2(path, out / name)
        shutil.copy2(BEFORE / (name + '.before'), out / (name + '.before'))
    arm = (REPO / 'include/linux/arm-smccc.h').read_text()
    shutil.copy2(REPO / 'include/linux/arm-smccc.h', out / 'arm-smccc.h')
    header, smc = sources['qcom_scm.h'], sources['qcom_scm-smc.c']
    definitions = [
        extract.block(header, 'enum qcom_scm_convention {'),
        extract.block(header, 'enum qcom_scm_arg_types {')]
    for name in ('MAX_QCOM_SCM_ARGS', 'MAX_QCOM_SCM_RETS', 'QCOM_SCM_ARGS_IMPL',
                 'QCOM_SCM_ARGS', 'SCM_SMC_FNID', 'QCOM_SCM_SVC_PIL',
                 'QCOM_SCM_PIL_PAS_INIT_IMAGE', 'QCOM_SCM_PIL_PAS_MEM_SETUP',
                 'QCOM_SCM_ERROR', 'QCOM_SCM_EINVAL_ADDR', 'QCOM_SCM_EINVAL_ARG',
                 'QCOM_SCM_EOPNOTSUPP', 'QCOM_SCM_ENOMEM', 'QCOM_SCM_V2_EBUSY'):
        definitions.append(macro(header, name))
    for name in ('ARM_SMCCC_STD_CALL', 'ARM_SMCCC_FAST_CALL', 'ARM_SMCCC_TYPE_SHIFT',
                 'ARM_SMCCC_SMC_32', 'ARM_SMCCC_SMC_64', 'ARM_SMCCC_CALL_CONV_SHIFT',
                 'ARM_SMCCC_OWNER_MASK', 'ARM_SMCCC_OWNER_SHIFT', 'ARM_SMCCC_FUNC_MASK',
                 'ARM_SMCCC_CALL_VAL', 'ARM_SMCCC_OWNER_SIP'):
        definitions.append(macro(arm, name))
    for name in ('SCM_SMC_N_REG_ARGS', 'SCM_SMC_FIRST_EXT_IDX', 'SCM_SMC_N_EXT_ARGS',
                 'SCM_SMC_FIRST_REG_IDX', 'SCM_SMC_LAST_REG_IDX'):
        definitions.append(macro(smc, name))
    definitions += [
        extract.block(header, 'struct qcom_scm_desc {'),
        extract.block(header, 'struct qcom_scm_res {'),
        extract.block(header, 'static inline int qcom_scm_remap_error('),
        extract.block(smc, 'struct arm_smccc_args {')]
    before_core = (BEFORE / 'qcom_scm.c.before').read_text()
    before_smc = (BEFORE / 'qcom_scm-smc.c.before').read_text()
    baseline = [
        extract.block(before_smc, 'int __scm_smc_call(').replace(
            'int __scm_smc_call(', 'static int before_smc_call(', 1),
        extract.block(before_core, 'static int __qcom_scm_pas_init_image(').replace(
            '__qcom_scm_pas_init_image(', 'before_image(', 1),
        extract.block(before_core, 'static int __qcom_scm_pas_mem_setup(').replace(
            '__qcom_scm_pas_mem_setup(', 'before_memory(', 1)]
    candidate = [
        extract.block(sources['qcom_scm.c'], 'bool qcom_scm_spx_pas_diag('),
        extract.block(smc, 'int __scm_smc_call('),
        extract.block(sources['qcom_scm.c'], 'static int __qcom_scm_pas_init_image('),
        extract.block(sources['qcom_scm.c'], 'static int __qcom_scm_pas_mem_setup(')]
    declarations = []
    for name, text in [
            ('spx_pas_diag', sources['qcom_scm.c']),
            ('spx_pas_image_diag_count', sources['qcom_scm.c']),
            ('spx_pas_mem_diag_count', sources['qcom_scm.c']),
            ('spx_pas_smc_diag_count', sources['qcom_scm-smc.c'])]:
        matches = re.findall(r'^static (?:bool|atomic_t) ' + name + r'\b[^;]*;', text, re.M)
        assert len(matches) == 1
        declarations.append(matches[0])
    parameter = re.findall(r'^module_param_named\(spx_pas_diag,[^\n]*;', sources['qcom_scm.c'], re.M)
    assert len(parameter) == 1
    declarations += parameter
    globals_text = '\n'.join(declarations)
    template = Path(__file__).with_name('native.in.c')
    shutil.copy2(template, out / template.name)
    shutil.copy2(__file__, out / Path(__file__).name)
    configured = template.read_text().replace('/* @DEFINITIONS */', '\n'.join(definitions))
    configured = configured.replace('/* @GLOBALS */', globals_text)
    candidate_text = '\n'.join(candidate)
    source = configured.replace('/* @BODIES */', '\n'.join(baseline) + '\n' + candidate_text)
    (out / 'native.c').write_text(source)
    cmd = ['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
           '-Wno-sign-compare',
           '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
           str(out / 'native.c'), '-o', str(out / 'native')]
    (out / 'compile-command.json').write_text(json.dumps(cmd, indent=2) + '\n')
    compiled = subprocess.run(cmd, capture_output=True, timeout=60)
    (out / 'compile.stdout').write_bytes(compiled.stdout)
    (out / 'compile.stderr').write_bytes(compiled.stderr)
    assert compiled.returncode == 0, compiled.stderr.decode()
    result = subprocess.run([str(out / 'native')], capture_output=True, timeout=30)
    (out / 'native.stdout').write_bytes(result.stdout)
    (out / 'native.stderr').write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr, result.stderr.decode()
    positive = json.loads(result.stdout)
    assert positive == dict(checks=91, before_after_cases=80, scope_cases=10, maximum_lines=32)
    controls = [
        ('wrong-pas-filter', 'desc->args[0] == 9', 'desc->args[0] == 8'),
        ('unbounded-log-budget', 'atomic_add_unless(&spx_pas_mem_diag_count, 1, 4)', 'true'),
        ('lost-service-result', 'return ret ? : res.result[0];', 'return ret;'),
        ('invalid-raw-result', 'if (ret)\n\t\t\tdev_info(dev, "SPX PAS diag smc done',
         'if (!ret)\n\t\t\tdev_info(dev, "SPX PAS diag smc done')]
    rejected = []
    for name, old, new in controls:
        assert candidate_text.count(old) == 1, name
        # The service-result mutation changes only the candidate memory body.
        changed = candidate_text.replace(old, new, 1)
        mutated = configured.replace('/* @BODIES */', '\n'.join(baseline) + '\n' + changed)
        control = out / 'controls' / name
        control.mkdir(parents=True)
        cfile = control / 'native.c'
        cfile.write_text(mutated)
        command = cmd[:-3] + [str(cfile), '-o', str(control / 'native')]
        compile_result = subprocess.run(command, capture_output=True, timeout=60)
        (control / 'compile.stdout').write_bytes(compile_result.stdout)
        (control / 'compile.stderr').write_bytes(compile_result.stderr)
        assert compile_result.returncode == 0, compile_result.stderr.decode()
        rejected_result = subprocess.run([str(control / 'native')], capture_output=True, timeout=30)
        (control / 'native.stdout').write_bytes(rejected_result.stdout)
        (control / 'native.stderr').write_bytes(rejected_result.stderr)
        assert rejected_result.returncode != 0, name
        rejected.append(dict(name=name, exit_code=rejected_result.returncode))
    assert source.count('static bool spx_pas_diag;') == 1
    control = out / 'controls/default-enabled'
    control.mkdir()
    cfile = control / 'native.c'
    cfile.write_text(source.replace('static bool spx_pas_diag;', 'static bool spx_pas_diag = true;', 1))
    compile_result = subprocess.run(cmd[:-3] + [str(cfile), '-o', str(control / 'native')],
                                    capture_output=True, timeout=60)
    (control / 'compile.stdout').write_bytes(compile_result.stdout)
    (control / 'compile.stderr').write_bytes(compile_result.stderr)
    assert compile_result.returncode == 0, compile_result.stderr.decode()
    rejected_result = subprocess.run([str(control / 'native')], capture_output=True, timeout=30)
    (control / 'native.stdout').write_bytes(rejected_result.stdout)
    (control / 'native.stderr').write_bytes(rejected_result.stderr)
    assert rejected_result.returncode != 0
    rejected.append(dict(name='default-enabled', exit_code=rejected_result.returncode))
    report = dict(actual_candidate_function_bodies=4, actual_baseline_function_bodies=3,
                  positive=positive, rejected_controls=rejected,
                  sanitizer='ASan/UBSan', kernel_atomic_and_clock_scm_leaf_operations_mocked=True,
                  hardware_operations=0, hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    hashes = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*')) if path.is_file()}
    (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps(report | {'manifest_sha256': sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
