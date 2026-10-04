#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare real-film H.264 fixtures and software references; no hardware codec use."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

ROOT = Path('/var/tmp/spx-video-media-20261003')
SOURCE = 'https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4.zip'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            h.update(data)
    return h.hexdigest()


def frame_rows(path):
    rows = []
    for line in path.read_text().splitlines():
        if line and not line.startswith('#'):
            fields = [value.strip() for value in line.split(',')]
            assert len(fields) == 6 and len(fields[-1]) == 32
            rows.append(dict(stream=int(fields[0]), dts=int(fields[1]), pts=int(fields[2]),
                             duration=int(fields[3]), bytes=int(fields[4]), md5=fields[5]))
    return rows


def main():
    (ROOT / 'prepare-started.json').open('x').write(json.dumps(dict(
        utc=datetime.now(timezone.utc).isoformat(), boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        release=os.uname().release, hardware_codec_used=False)) + '\n')
    shutil.copy2(__file__, ROOT / 'prepare.py')
    archive = ROOT / 'bbb_sunflower_1080p_30fps_normal.mp4.zip'
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        videos = [row for row in entries if row.filename.endswith('.mp4')]
        assert len(videos) == 1 and 0 < videos[0].file_size < 400000000
        assert not videos[0].flag_bits & 1
        video = ROOT / 'source.mp4'
        with source.open(videos[0]) as data, video.open('xb') as out:
            shutil.copyfileobj(data, out)
    commands = []

    def run(label, argv, timeout=240):
        start = time.monotonic()
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        (ROOT / (label + '.stdout')).write_bytes(result.stdout)
        (ROOT / (label + '.stderr')).write_bytes(result.stderr)
        commands.append(dict(label=label, argv=argv, exit_code=result.returncode,
                             seconds=round(time.monotonic() - start, 3)))
        (ROOT / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, label
        print(json.dumps(commands[-1]), flush=True)
        return result.stdout

    run('ffmpeg-version', ['ffmpeg', '-version'])
    run('ffprobe-version', ['ffprobe', '-version'])
    run('decoders', ['ffmpeg', '-hide_banner', '-decoders'])
    run('encoders', ['ffmpeg', '-hide_banner', '-encoders'])
    source_probe = json.loads(run('source-probe', ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-of', 'json', str(video)]))
    stream = source_probe['streams'][0]
    assert stream['codec_name'] == 'h264' and stream['width'] == 1920 and stream['height'] == 1080
    ff = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'info', '-n']
    raw = ROOT / 'film-640x360-120f.nv12'
    run('raw-film', ff + ['-ss', '30', '-c:v', 'h264', '-i', str(video), '-map', '0:v:0', '-an',
        '-vf', 'scale=640:360,format=nv12,fps=30', '-frames:v', '120', '-threads', '1',
        '-f', 'rawvideo', str(raw)])
    assert raw.stat().st_size == 640 * 360 * 3 // 2 * 120
    inputs = ['-f', 'rawvideo', '-pixel_format', 'nv12', '-video_size', '640x360',
              '-framerate', '30', '-i', str(raw), '-an', '-frames:v', '120']
    clips = []
    for label, profile, bf in (('baseline', 'baseline', '0'), ('high-bframes', 'high', '2')):
        clip = ROOT / (label + '.h264')
        run(label + '-encode-software', ff + inputs + ['-c:v', 'libx264', '-threads', '1',
            '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-profile:v', profile,
            '-level:v', '3.0', '-g', '30', '-bf', bf, '-f', 'h264', str(clip)])
        probe = json.loads(run(label + '-probe', ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-count_frames', '-show_streams', '-of', 'json', str(clip)]))['streams'][0]
        assert probe['width'] == 640 and probe['height'] == 360 and int(probe['nb_read_frames']) == 120
        assert probe['codec_name'] == 'h264' and probe['pix_fmt'] == 'yuv420p'
        reference = ROOT / (label + '-reference.framemd5')
        run(label + '-reference', ff + ['-c:v', 'h264', '-i', str(clip), '-map', '0:v:0',
            '-an', '-pix_fmt', 'yuv420p', '-threads', '1', '-f', 'framemd5', str(reference)])
        rows = frame_rows(reference)
        assert len(rows) == 120 and all(row['bytes'] == 345600 for row in rows)
        repeat = ROOT / (label + '-repeat.framemd5')
        run(label + '-reference-repeat', ff + ['-c:v', 'h264', '-i', str(clip), '-map', '0:v:0',
            '-an', '-pix_fmt', 'yuv420p', '-threads', '1', '-f', 'framemd5', str(repeat)])
        assert frame_rows(repeat) == rows
        clips.append(dict(name=label, file=clip.name, sha256=sha(clip), profile=probe['profile'],
                          frames=120, width=640, height=360, frame_bytes=345600,
                          reference=reference.name, reference_sha256=sha(reference),
                          reference_repeat_exact=True))
    attribution = ('Big Buck Bunny: (c) copyright 2008, Blender Foundation / www.bigbuckbunny.org\n'
                   'Film project license: Creative Commons Attribution 3.0.\n'
                   'https://peach.blender.org/about/\n'
                   'Source download: ' + SOURCE + '\n'
                   'Sunflower 1080p30 distribution; source and derived excerpts are diagnostic fixtures.\n')
    (ROOT / 'ATTRIBUTION.txt').write_text(attribution)
    result = dict(utc=datetime.now(timezone.utc).isoformat(), source_url=SOURCE,
                  source_zip_sha256=sha(archive), source_video_sha256=sha(video),
                  source_video_zip_entry=videos[0].filename,
                  ffmpeg_sha256=sha(Path('/usr/bin/ffmpeg')), ffprobe_sha256=sha(Path('/usr/bin/ffprobe')),
                  raw_input=raw.name, raw_input_sha256=sha(raw), clips=clips,
                  hardware_codec_used=False, media_acceptance_passed=False,
                  limits=['Software references and a four-second real-film excerpt only.',
                          'Hardware codec execution, output comparison, performance and idle/resume remain untested.',
                          'Computed source hashes record the download; no publisher checksum/signature was supplied.'])
    (ROOT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    files = {str(p.relative_to(ROOT)): sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file()}
    (ROOT / 'sha256.json').write_text(json.dumps(files, indent=2) + '\n')
    print(json.dumps(dict(clips=len(clips), files=len(files), manifest_sha256=sha(ROOT / 'sha256.json'))))


if __name__ == '__main__':
    main()
