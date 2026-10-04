#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Seal a read-only D03 inventory on AX's verified known-good return."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

BOOT = 'b6b4f20b-376f-4577-b282-677ad4ae0ec8'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    sys.dont_write_bytecode = True
    sys.path.insert(0, '/usr/local/lib/spx-boot-diagnostics')
    import ax_boot_guard as guard
    assert os.geteuid() == 0 and os.uname().release == '6.18.3-1-surface+'
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert 'spx_boot=known-good' in Path('/proc/cmdline').read_text().split()
    a = guard.load()
    env = guard.recovery(a)
    assert env.get('next_entry', '') == ''
    returned = json.loads((guard.X/'return-result/result.json').read_text())
    assert returned['returned_boot_id'] == BOOT and returned['original_rtc_copy_exact']
    out = Path(sys.argv[1])
    out.mkdir(mode=0o700)
    started = time.clock_gettime(time.CLOCK_BOOTTIME)
    shutil.copyfile(Path(__file__), out/'collect_video_state.py')
    reads = {'cmdline.txt':'/proc/cmdline','boot-id.txt':'/proc/sys/kernel/random/boot_id',
             'taint.txt':'/proc/sys/kernel/tainted','modules.txt':'/proc/modules',
             'iomem.txt':'/proc/iomem', 'live.dtb':'/sys/firmware/fdt'}
    for name, source in reads.items():
        (out/name).write_bytes(Path(source).read_bytes())
    (out/'known-good.config').write_bytes(gzip.decompress(Path('/proc/config.gz').read_bytes()))
    for name, source in [('ax.config',guard.X/'build/config-extracted'),
                         ('ax.dtb',guard.X/'build/dtb-build/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb')]:
        if source.exists():
            shutil.copyfile(source,out/name)
    commands = [['uname','-a'], ['dtc','-I','dtb','-O','dts','-o',str(out/'live.dts'),str(out/'live.dtb')],
                ['journalctl','-b','-k','--no-pager','-o','short-monotonic'],
                ['ffmpeg','-version'], ['ffmpeg','-hide_banner','-decoders'],
                ['ffmpeg','-hide_banner','-encoders'], ['v4l2-ctl','--version']]
    outcomes=[]
    for index, cmd in enumerate(commands):
        result=subprocess.run(cmd,capture_output=True,timeout=30)
        (out/f'command-{index}.stdout').write_bytes(result.stdout)
        (out/f'command-{index}.stderr').write_bytes(result.stderr)
        outcomes.append(dict(argv=cmd,returncode=result.returncode))
        assert result.returncode == 0, cmd
    nodes={name:[dict(name=p.name,target=str(p.resolve())) for p in sorted(Path(root).glob(pattern))]
           for name,root,pattern in [('video','/dev','video*'),('media','/dev','media*'),
                                    ('video4linux','/sys/class/video4linux','*'),
                                    ('media-class','/sys/class/media','*')]}
    codec_platforms=[]
    for node in sorted(Path('/sys/bus/platform/devices').iterdir()):
        if any(s in node.name.lower() for s in ('venus','video-codec','iris','aa00000')):
            codec_platforms.append(dict(name=node.name,target=str(node.resolve())))
    config=(out/'known-good.config').read_text()
    selected=lambda text:{name:next((line for line in text.splitlines() if line.startswith(name+'=') or line=='# '+name+' is not set'), 'absent from effective config')
                         for name in ['CONFIG_VIDEO_QCOM_VENUS','CONFIG_VIDEO_QCOM_IRIS',
                                      'CONFIG_V4L_MEM2MEM_DRIVERS','CONFIG_V4L2_MEM2MEM_DEV','CONFIG_QCOM_MDT_LOADER']}
    report=dict(boot_id=BOOT,release=os.uname().release,started_boottime=started,
                finished_boottime=time.clock_gettime(time.CLOCK_BOOTTIME), nodes=nodes,
                codec_platforms=codec_platforms,taint=(out/'taint.txt').read_text().strip(),
                configuration={'known_good':selected(config),'ax':selected((out/'ax.config').read_text())},
                commands=outcomes,env=env,codec_nodes_opened=0,codec_commands=0,
                firmware_loaded=False,boot_selected=False,hardware_acceptance_closed=False)
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert Path('/proc/sys/kernel/tainted').read_bytes() == (out/'taint.txt').read_bytes()
    assert not guard.recovery(a).get('next_entry','')
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    hashes={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    assert all(sha(out/name)==digest for name,digest in hashes.items())
    os.sync()
    print(json.dumps(report|{'files_verified':len(hashes),'manifest_sha256':sha(out/'sha256.json')},indent=2))


if __name__ == '__main__':
    main()
