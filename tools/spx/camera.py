# SPDX-License-Identifier: GPL-2.0-only
"""Bounded rear-camera capture on a running trial: three raw frames, then off.

The frames stay in the attempt directory (root only). Every step is written
and synced before the next one, because a wedged STREAMON loses anything that
is still in the page cache.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

SENSOR = 'ov13858'
CODE, SIZE, PIXEL = 'SGRBG10_1X10', '2112x1568', 'pgAA'
CSID, RDI, VIDEO = 'msm_csid0', 'msm_vfe0_rdi0', 'msm_vfe0_video0'
FRAMES = 3
LED = Path('/sys/class/leds/spx:rear:privacy/brightness')
SUMMARY = Path('/sys/kernel/debug/regulator/regulator_summary')


def call(argv, timeout=15):
    """Run one hardware call without waiting forever on an unkillable task."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return dict(argv=argv, returncode=proc.returncode, output=out)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = ''
        return dict(argv=argv, timed_out=True, output=out)


def rails():
    try:
        text = SUMMARY.read_text()
    except OSError as error:
        return str(error)
    keep = re.compile(r'spx-camera|ldo5\b|ldo3\b|camss|4-0010|\d-0010')
    return [line.rstrip() for line in text.splitlines() if keep.search(line)]


def entity(graph, name):
    """Return the text block of one entity from `media-ctl -p`."""
    match = re.search(r'^- entity \d+: ' + re.escape(name) + r'[ (].*?(?=^- entity |\Z)', graph, re.M | re.S)
    return match.group(0) if match else None


def analyse(path, width, height, stride, sizeimage, out):
    """Per-frame statistics on the 8 MSBs, and a small preview of the last frame."""
    data = path.read_bytes()
    frames = []
    for index in range(len(data) // sizeimage):
        frame = data[index * sizeimage:(index + 1) * sizeimage]
        values = []
        for row in range(0, height, 16):
            line = frame[row * stride:row * stride + width * 5 // 4]
            # MIPI RAW10: four MSB bytes, then one byte holding the LSB pairs.
            values.extend(b for i, b in enumerate(line) if i % 5 != 4)
        mean = sum(values) / len(values)
        spread = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        frames.append(dict(samples=len(values), minimum=min(values), maximum=max(values),
                           mean=round(mean, 2), stddev=round(spread, 2),
                           distinct=len(set(values)),
                           all_a5=all(b == 0xa5 for b in frame[:4096]),
                           all_zero=not any(frame[::257])))
    if frames:
        frame = data[-sizeimage:]
        rows = []
        for row in range(0, height, 8):
            line = frame[row * stride:row * stride + width * 5 // 4]
            rows.append(bytes(line[i] for i in range(0, len(line), 10)))
        preview = out / 'preview.pgm'
        preview.write_bytes(b'P5\n%d %d\n255\n' % (len(rows[0]), len(rows)) + b''.join(rows))
    return frames


def exercise(out, attempt, release):
    out.mkdir(mode=0o700)
    result = dict(attempt=attempt, release=release, complete=False, steps=[],
                  boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    target = out / 'result.json'

    def save():
        temporary = target.with_suffix('.tmp')
        with temporary.open('w') as stream:
            stream.write(json.dumps(result, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.sync()

    def step(name, argv, timeout=15):
        record = call(argv, timeout)
        record['name'] = name
        result['steps'].append(record)
        save()
        return record

    def fail(reason):
        result['error'] = reason
        result['rails_after'] = rails()
        step('kernel-log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic',
                            '-g', 'camss|csiphy|csid|vfe|ov13858|cci|arm-smmu|ac65000'], 30)
        save()
        return result

    save()
    step('modprobe', ['modprobe', 'qcom-camss'], 30)
    media = graph = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and media is None:
        for node in sorted(Path('/dev').glob('media*')):
            listing = call(['media-ctl', '-d', str(node), '-p'])
            if 'msm_csiphy' in listing.get('output', ''):
                media, graph = str(node), listing['output']
                break
        else:
            time.sleep(2)
    result['rails_before'] = rails()
    if media is None:
        return fail('no camss media device')
    (out / 'graph.txt').write_text(graph)
    result['media'] = media
    name = re.search(r'^- entity \d+: (' + SENSOR + r' [^ (]+)', graph, re.M)
    if not name:
        return fail('sensor is not in the camss graph')
    sensor = name.group(1)
    block = entity(graph, sensor)
    phy = re.search(r'msm_csiphy\d+', block)
    subdev = re.search(r'/dev/v4l-subdev\d+', block)
    video = re.search(r'/dev/video\d+', entity(graph, VIDEO) or '')
    csid = re.search(r'/dev/v4l-subdev\d+', entity(graph, CSID) or '')
    if not (phy and subdev and video and csid):
        return fail('graph is missing the sensor link, a subdevice or the video node')
    phy, subdev, video, csid = phy.group(0), subdev.group(0), video.group(0), csid.group(0)
    result.update(sensor=sensor, phy=phy, video=video)
    save()

    step('csid-pattern-off', ['v4l2-ctl', '-d', csid, '--set-ctrl=test_pattern=0'])
    step('sensor-pattern-off', ['v4l2-ctl', '-d', subdev, '--set-ctrl=test_pattern=0'])
    for source, sink in ((phy, CSID), (CSID, RDI), (RDI, VIDEO)):
        linked = step('link-' + sink, ['media-ctl', '-d', media, '-l', "'%s':1 -> '%s':0 [1]" % (source, sink)])
        if linked.get('returncode') != 0:
            return fail('link to ' + sink + ' failed')
    step('sensor-format', ['media-ctl', '-d', media, '-V', "'%s':0 [fmt:%s/%s]" % (sensor, CODE, SIZE)])
    actual = step('sensor-format-read', ['media-ctl', '-d', media, '--get-v4l2', "'%s':0" % sensor])
    found = re.search(r'fmt:([A-Z0-9_]+)/(\d+)x(\d+)', actual.get('output', ''))
    if not found:
        return fail('sensor format could not be read')
    code, width, height = found.group(1), int(found.group(2)), int(found.group(3))
    for name in (phy, CSID, RDI):
        step('format-' + name, ['media-ctl', '-d', media, '-V', "'%s':0 [fmt:%s/%dx%d]" % (name, code, width, height)])
    step('video-format', ['v4l2-ctl', '-d', video, '--set-fmt-video=width=%d,height=%d,pixelformat=%s' % (width, height, PIXEL)])
    shown = step('video-format-read', ['v4l2-ctl', '-d', video, '--get-fmt-video'])
    stride = re.search(r'Bytes per Line\s*:\s*(\d+)', shown.get('output', ''))
    sizeimage = re.search(r'Size Image\s*:\s*(\d+)', shown.get('output', ''))
    if not (stride and sizeimage):
        return fail('video format could not be read')
    stride, sizeimage = int(stride.group(1)), int(sizeimage.group(1))
    result.update(width=width, height=height, stride=stride, sizeimage=sizeimage,
                  iommu=Path('/sys/bus/platform/devices/ac65000.camss/iommu_group').exists())
    save()

    raw = out / 'frames.raw'
    result['stream_started'] = time.time()
    save()
    proc = subprocess.Popen(['v4l2-ctl', '-d', video, '--stream-mmap=4', '--stream-count=%d' % FRAMES,
                             '--stream-to=' + str(raw)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    try:
        result['led_during'] = LED.read_text().strip()
    except OSError as error:
        result['led_during'] = str(error)
    result['rails_during'] = rails()
    save()
    try:
        output, _ = proc.communicate(timeout=25)
        result['stream'] = dict(returncode=proc.returncode, output=output)
    except subprocess.TimeoutExpired:
        proc.kill()
        result['stream'] = dict(timed_out=True)
        save()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            return fail('capture process is wedged')
    save()
    time.sleep(2)
    try:
        result['led_after'] = LED.read_text().strip()
    except OSError as error:
        result['led_after'] = str(error)
    result['rails_after'] = rails()
    step('kernel-log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic',
                        '-g', 'camss|csiphy|csid|vfe|ov13858|cci|arm-smmu|ac65000'], 30)
    size = raw.stat().st_size if raw.exists() else 0
    result['bytes'] = size
    if result['stream'].get('returncode') != 0 or size < sizeimage:
        return fail('no complete frame was captured')
    result['frames'] = analyse(raw, width, height, stride, sizeimage, out)
    # Varied, non-fill data shows frames arrived. A person still has to look at
    # preview.pgm to say that it is the scene in front of the camera.
    result['complete'] = all(f['distinct'] > 16 and not f['all_a5'] and not f['all_zero']
                             for f in result['frames'])
    save()
    return result
