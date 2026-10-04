#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded real-film H.264 decode/encode on an actually bound BB Venus device."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback

X = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bb')
FIXTURE = Path('/var/lib/spx-boot-diagnostics/fixtures/video-media-20261003')
MANIFEST = '3a251cbe1a6d72a1601011d260a85f4faaa6519e111ff97ca0d824f68d0aa612'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def frames(path):
    rows = [[x.strip() for x in line.split(',')] for line in path.read_text().splitlines()
            if line and not line.startswith('#')]
    assert len(rows) == 120 and all(len(row) == 6 for row in rows)
    assert all(int(row[0]) == 0 and int(row[4]) == 345600 and
               re.fullmatch('[0-9a-f]{32}', row[5]) for row in rows)
    assert all([int(row[1]), int(row[2]), int(row[3])] == [index, index, 1]
               for index, row in enumerate(rows))
    return [row[5] for row in rows]


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    a = read(X / 'attempt.json')
    assert a == read(X.parent.parent / 'attempt.json')
    bid = Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    def identity():
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == bid
        assert a['attempt'] == '20261004bb' and os.uname().release == a['release'] == '7.3.0-rc2-spx-mainline-20261004bb+'
        assert Path('/proc/cmdline').read_text().split() == ['BOOT_IMAGE=/spx-trial-20261004bb/vmlinuz'] + a['cmdline'].split()
        assert Path('/proc/sys/kernel/tainted').read_text().strip() == '0'
        assert subprocess.check_output(['systemctl', 'is-active', 'spx-bb-fallback.timer'], text=True).strip() == 'active'
        env = subprocess.check_output(['grub-editenv', '/boot/grub/grubenv', 'list'], text=True).splitlines()
        assert 'saved_entry=spx-known-good' in env and not any(x.startswith('next_entry=') and x != 'next_entry=' for x in env)

    identity()
    age = float(Path('/proc/uptime').read_text().split()[0])
    assert 100 <= age < 450, age
    startup = read(X / 'video-startup/result.json')
    assert startup['boot_id'] == bid and startup['release'] == a['release']
    assert any(row['driver'] and row['driver'].endswith('/qcom-venus') for row in startup['platform_devices'])
    names = {row['name']: row['device'] for row in startup['video_nodes']}
    assert {'qcom-venus-decoder', 'qcom-venus-encoder'} <= set(names)
    for label, node in names.items():
        if label in ('qcom-venus-decoder', 'qcom-venus-encoder'):
            path = Path('/sys/class/video4linux') / Path(node).name
            assert (path / 'name').read_text().strip() == label
            assert 'aa00000.video-codec' in str(path.resolve())
    assert sha(FIXTURE / 'sha256.json') == MANIFEST
    for name, digest in read(FIXTURE / 'sha256.json').items():
        assert sha(FIXTURE / name) == digest, name
    fixture = read(FIXTURE / 'result.json')
    assert sha(Path('/usr/bin/ffmpeg')) == fixture['ffmpeg_sha256']
    assert sha(Path('/usr/bin/ffprobe')) == fixture['ffprobe_sha256']
    for name, digest in a['sha256'].items():
        assert sha(Path(name)) == digest
    out = X / 'media-short-result'
    out.mkdir(mode=0o700)
    shutil.copy2(__file__, out / Path(__file__).name)
    runs = []

    def run(label, argv, expected_node=None, timeout=45):
        identity()
        start = time.monotonic()
        witnesses = []
        with (out / (label + '.stdout')).open('xb') as stdout, (out / (label + '.stderr')).open('xb') as stderr:
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
            expired = False
            while process.poll() is None:
                nodes = []
                for fd in Path(f'/proc/{process.pid}/fd').glob('*'):
                    try:
                        target = os.readlink(fd)
                        if target.startswith('/dev/video'):
                            nodes.append(target)
                    except OSError:
                        pass
                if nodes:
                    witnesses.append(dict(seconds=round(time.monotonic() - start, 4), nodes=sorted(set(nodes))))
                if time.monotonic() - start >= timeout:
                    expired = True
                    process.kill()
                    break
                time.sleep(0.005)
            rc = process.wait(timeout=5)
        row = dict(label=label, argv=argv, pid=process.pid, exit_code=rc, timed_out=expired,
                   elapsed_seconds=round(time.monotonic() - start, 3), fd_witnesses=witnesses,
                   expected_venus_node=expected_node)
        runs.append(row)
        (out / 'runs.json').write_text(json.dumps(runs, indent=2) + '\n')
        assert rc == 0 and not expired, row['label']
        if expected_node:
            assert any(expected_node in sample['nodes'] for sample in witnesses), label
        identity()

    verdict = dict(utc=datetime.now(timezone.utc).isoformat(), boot_id=bid, release=a['release'],
                   uptime_start=age, fixture_manifest_sha256=MANIFEST,
                   hardware_acceptance_closed=False, scoped_passed=False)
    try:
        ff = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'verbose', '-n']
        decodes = []
        for clip in fixture['clips']:
            target = out / (clip['name'] + '-hardware.framemd5')
            run(clip['name'] + '-decode', ff + ['-c:v', 'h264_v4l2m2m', '-i', str(FIXTURE / clip['file']),
                '-map', '0:v:0', '-an', '-pix_fmt', 'yuv420p', '-threads', '1', '-f', 'framemd5', str(target)],
                names['qcom-venus-decoder'])
            assert frames(target) == frames(FIXTURE / clip['reference'])
            decodes.append(dict(clip=clip['name'], frames=120, frame_pixels_exact=True))
        encoded = out / 'hardware-encoded.h264'
        run('encode', ff + ['-f', 'rawvideo', '-pixel_format', 'nv12', '-video_size', '640x360',
            '-framerate', '30', '-i', str(FIXTURE / fixture['raw_input']), '-an', '-frames:v', '120',
            '-c:v', 'h264_v4l2m2m', '-b:v', '2000000', '-g', '30', '-f', 'h264', str(encoded)],
            names['qcom-venus-encoder'])
        run('encoded-probe', ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
            '-show_streams', '-of', 'json', str(encoded)])
        stream = read(out / 'encoded-probe.stdout')['streams'][0]
        assert stream['codec_name'] == 'h264' and stream['width'] == 640 and stream['height'] == 360
        assert int(stream['nb_read_frames']) == 120
        run('encoded-quality', ff + ['-f', 'rawvideo', '-pixel_format', 'nv12', '-video_size', '640x360',
            '-framerate', '30', '-i', str(FIXTURE / fixture['raw_input']), '-c:v', 'h264', '-i', str(encoded),
            '-filter_complex', '[0:v]format=yuv420p,setpts=PTS-STARTPTS[a];[1:v]format=yuv420p,setpts=PTS-STARTPTS[b];[a][b]psnr=stats_file=' + str(out / 'psnr.log'),
            '-frames:v', '120', '-an', '-f', 'null', '-'])
        psnr = re.findall(r'PSNR .*?average:([\d.]+|inf)', (out / 'encoded-quality.stderr').read_text())
        assert len(psnr) == 1 and float(psnr[0]) >= 32
        assert len((out / 'psnr.log').read_text().splitlines()) == 120
        verdict.update(scoped_passed=True, decodes=decodes, encoder_frames=120,
                       encoder_average_psnr_db=psnr[0])
    except BaseException:
        verdict['failure'] = traceback.format_exc()
    finally:
        for name, argv in (('kernel', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic']),
                           ('clocks', ['cat', '/sys/kernel/debug/clk/clk_summary']),
                           ('genpd', ['cat', '/sys/kernel/debug/pm_genpd/pm_genpd_summary'])):
            result = subprocess.run(argv, capture_output=True, timeout=30)
            (out / (name + '.stdout')).write_bytes(result.stdout)
            (out / (name + '.stderr')).write_bytes(result.stderr)
        verdict['uptime_end'] = float(Path('/proc/uptime').read_text().split()[0])
        if Path('/proc/sys/kernel/tainted').read_text().strip() != '0' or re.search(
                r'\b(?:BUG:|Oops:|WARNING:|Unhandled context fault|Unhandled fault)',
                (out / 'kernel.stdout').read_text()):
            verdict['scoped_passed'] = False
            verdict['kernel_fault_or_taint'] = True
        verdict['limits'] = ['Two four-second H.264 decodes and one four-second encode only.',
                             'FD witnesses and explicit V4L2 codecs required; no software fallback counts as hardware.',
                             'Sustained playback, other codecs, secure media, idle/resume and final-candidate regression remain open.']
        (out / 'result.json').write_text(json.dumps(verdict, indent=2, allow_nan=False) + '\n')
        hashes = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*')) if path.is_file()}
        (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
        os.sync()
    assert verdict['scoped_passed'], verdict.get('failure')


if __name__ == '__main__':
    main()
