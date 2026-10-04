#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pin BA's PAS errno ambiguity and retained PIL declarations without hardware writes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
import ba_boot_guard as guard


def main():
    os.umask(0o077)
    a = guard.load()
    boot = guard.trial_identity(a)
    out = guard.X / 'pas-failure-provenance'
    out.mkdir(mode=0o700)
    sources = json.loads((guard.X / 'build/source-files.json').read_text())
    for name in ('drivers/soc/qcom/mdt_loader.c',
                 'drivers/firmware/qcom/qcom_scm.c',
                 'drivers/firmware/qcom/qcom_scm.h',
                 'drivers/firmware/qcom/qcom_scm-smc.c',
                 'drivers/firmware/qcom/qcom_scm_trace.h',
                 'drivers/firmware/qcom/qcom_pas.c',
                 'drivers/media/platform/qcom/venus/firmware.c'):
        source = guard.REPO / name
        assert guard.sha(source) == sources[name]['sha256']
        shutil.copy2(source, out / source.name)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(guard.X / 'build/config-extracted', out / 'candidate.config')
    shutil.copy2(guard.X / 'video-startup/kernel.stdout', out / 'startup-kernel.log')
    shutil.copy2(guard.X / 'startup-review/report.json', out / 'startup-review.json')
    vendor = Path('/home/dvitali/Documents/drivers/FileRepository')
    inputs = (
        vendor / 'qcpil8180.inf_arm64_33f5ea4e4b666c6f/qcpil8180.inf',
        vendor / 'surfaceprox_pilext.inf_arm64_dd37e6cf77efa22b/surfaceprox_pilext.inf')
    provenance = []
    for source in inputs:
        shutil.copy2(source, out / source.name)
        text = source.read_text(encoding='utf-16')
        (out / (source.name + '.utf8')).write_text(text)
        provenance.append(dict(path=str(source), sha256=guard.sha(source),
            driver_version=[line for line in text.splitlines() if line.startswith('DriverVer')]))
    extension = (out / 'surfaceprox_pilext.inf.utf8').read_text()
    venus = [line for line in extension.splitlines() if 'SubsystemLoad\\VENUS,' in line]
    assert venus == [
        'HKR ,SubsystemLoad\\VENUS,MemoryAlignment,%REG_DWORD%,0',
        'HKR ,SubsystemLoad\\VENUS,MemoryReservation,%REG_DWORD%,0x00500000']
    config = (out / 'candidate.config').read_text().splitlines()
    assert '# CONFIG_FTRACE is not set' in config
    assert 'CONFIG_EVENT_TRACING=y' not in config and 'CONFIG_TRACEPOINTS=y' not in config
    scm = (out / 'qcom_scm.c').read_text()
    start = scm.index('static int __qcom_scm_pas_mem_setup(')
    stop = scm.index('\nint qcom_scm_pas_mem_setup(', start)
    body = scm[start:stop]
    assert '.arginfo = QCOM_SCM_ARGS(3)' in body
    assert '.args[0] = pas_id' in body and '.args[1] = addr' in body and '.args[2] = size' in body
    assert 'return ret ? : res.result[0];' in body
    assert 'qcom_scm_clk_enable()' in body and 'qcom_scm_bw_enable()' in body
    trace = (out / 'qcom_scm_trace.h').read_text()
    assert 'TRACE_EVENT(scm_smc_request,' in trace and 'TRACE_EVENT(scm_smc_done,' in trace
    report = dict(utc=datetime.now(timezone.utc).isoformat(), actual_boot_id=boot,
        release=a['release'], compiled_source_hashes_verified=7, vendor_inputs=provenance,
        retained_venus_memory_declarations=venus,
        retained_declaration_has_fixed_venus_memory_address=False,
        secure_service_accepts_current_reservation_unproven=True,
        caller_memory_setup_arguments=['PAS9', '0xfe500000', '0x500000'],
        memory_setup_errno=-22, errno_origin_unresolved=True,
        possible_origins=['SCM clock setup', 'SCM bandwidth setup',
                          'SCM transport/remapped result', 'PAS service result'],
        existing_source_has_request_and_raw_result_trace_events=True,
        running_candidate_event_tracing_disabled=True,
        event_tracing_enabled_or_hardware_retried=False,
        vendor_driver_executed=False, boot_selection_changed=False,
        firmware_authentication_passed=False, hardware_acceptance_closed=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'sha256.json').write_text(json.dumps(guard.files(out), indent=2) + '\n')
    os.sync()
    assert guard.trial_identity(a) == boot
    print(json.dumps(report | {'manifest_sha256': guard.sha(out / 'sha256.json')}, indent=2))


if __name__ == '__main__':
    main()
