# SPDX-License-Identifier: GPL-2.0-only
"""Bounded rear-camera capture on a running trial: three raw frames, then off.

The frames stay in the attempt directory (root only). Every step is written
and synced before the next one, because a wedged STREAMON loses anything that
is still in the page cache.
"""
import json
from collections import Counter
import os
import re
import subprocess
import time
from pathlib import Path

SENSOR = 'ov13858'
CODE, SIZE, PIXEL = 'SGRBG10_1X10', '2112x1568', 'pgAA'
CSID, RDI, VIDEO = 'msm_csid0', 'msm_vfe0_rdi0', 'msm_vfe0_video0'
FRAMES = 3
BRIGHT_WAIT = 45
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


def preview(frame, width, height, stride, destination):
    """Demosaic RAW10 as GRBG, then apply one common 0.2–99.8% stretch.

    Preserve sensor orientation and channel ratios: this diagnostic preview
    does not supply camera mounting rotation, white balance or calibration.
    """
    if width % 4 or height % 2 or stride < width * 5 // 4 or len(frame) < stride * height:
        raise ValueError('invalid packed RAW10 dimensions or truncated frame')
    bayer = bytearray(width * height)
    for row in range(height):
        line = frame[row * stride:row * stride + width * 5 // 4]
        for phase in range(4):
            bayer[row * width + phase:(row + 1) * width:4] = line[phase::5]
    converted = subprocess.run(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
         '-pixel_format', 'bayer_grbg8', '-video_size', '%dx%d' % (width, height),
         '-i', 'pipe:0', '-frames:v', '1', '-pix_fmt', 'rgb24',
         '-f', 'rawvideo', 'pipe:1'], input=bayer, capture_output=True,
        check=True, timeout=30)
    rgb = converted.stdout
    if len(rgb) != width * height * 3:
        raise ValueError('incomplete demosaiced frame')
    histogram = Counter(rgb)

    def percentile(fraction):
        count = 0
        for value in range(256):
            count += histogram[value]
            if count > int((len(rgb) - 1) * fraction):
                return value

    low, high = percentile(0.002), percentile(0.998)
    # Preserve a flat frame instead of manufacturing contrast in it.
    table = bytes(max(0, min(255, round((v - low) * 255 / (high - low))))
                  for v in range(256)) if high > low else bytes(range(256))
    destination.write_bytes(b'P6\n%d %d\n255\n' % (width, height) + rgb.translate(table))
    return dict(file=destination.name, bayer='GRBG', low=low, high=high,
                rotation=0, colour_calibrated=False)


def analyse(path, width, height, stride, sizeimage, out, label='scene'):
    """Per-frame statistics and a demosaiced preview of the last complete frame."""
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
        frame = data[(len(frames) - 1) * sizeimage:len(frames) * sizeimage]
        destination = out / ('preview.ppm' if label == 'scene' else 'preview-%s.ppm' % label)
        try:
            frames[-1]['preview'] = preview(frame, width, height, stride, destination)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            # A rendering failure must not interrupt capture cleanup or discard
            # the raw-frame evidence (including on systems without FFmpeg).
            frames[-1]['preview_error'] = str(error)
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

    def grab(label, filename):
        """Stream FRAMES buffers to one file; return the capture record or None if it wedged."""
        raw = out / filename
        record = dict(started=time.time())
        proc = subprocess.Popen(['v4l2-ctl', '-d', video, '--stream-mmap=4', '--stream-count=%d' % FRAMES,
                                 '--stream-to=' + str(raw)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(2)
        try:
            record['led_during'] = LED.read_text().strip()
        except OSError as error:
            record['led_during'] = str(error)
        record['rails_during'] = rails()
        try:
            output, _ = proc.communicate(timeout=25)
            record['stream'] = dict(returncode=proc.returncode, output=output)
        except subprocess.TimeoutExpired:
            proc.kill()
            record['stream'] = dict(timed_out=True)
            result[label] = record
            save()
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                return None
        record['bytes'] = raw.stat().st_size if raw.exists() else 0
        if record['stream'].get('returncode') == 0 and record['bytes'] >= sizeimage:
            record['frames'] = analyse(raw, width, height, stride, sizeimage, out, label)
        result[label] = record
        save()
        return record

    def informative(record):
        return bool(record and record.get('frames')) and all(
            f['distinct'] > 16 and not f['all_a5'] and not f['all_zero'] for f in record['frames'])

    # 1. The scene as the sensor sees it with its default exposure.
    result['stream_started'] = time.time()
    save()
    scene = grab('scene', 'frames.raw')
    if scene is None:
        return fail('capture process is wedged')
    result['led_during'], result['led_after'] = scene.get('led_during'), None
    result['rails_during'] = scene.get('rails_during')
    time.sleep(2)
    try:
        result['led_after'] = LED.read_text().strip()
    except OSError as error:
        result['led_after'] = str(error)
    result['rails_after'] = rails()
    step('kernel-log', ['journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic',
                        '-g', 'camss|csiphy|csid|vfe|ov13858|cci|arm-smmu|ac65000'], 30)
    result['bytes'] = scene['bytes']
    result['stream'] = scene['stream']
    if scene['stream'].get('returncode') != 0 or scene['bytes'] < sizeimage:
        return fail('no complete frame was captured')
    result['frames'] = scene['frames']

    # 2. A flat scene is either darkness or a dead path. The sensor's own colour
    # bars cross the same CSIPHY/CSID/VFE/IOMMU path with known content.
    if not informative(scene):
        step('sensor-pattern-bars', ['v4l2-ctl', '-d', subdev, '--set-ctrl=test_pattern=1'])
        if grab('pattern', 'frames-pattern.raw') is None:
            return fail('pattern capture is wedged')
        step('sensor-pattern-off-again', ['v4l2-ctl', '-d', subdev, '--set-ctrl=test_pattern=0'])
        # 3. The scene again after a pause (time to aim the camera at a lit
        # subject), with exposure and analogue gain raised well above default.
        time.sleep(BRIGHT_WAIT)
        step('exposure-up', ['v4l2-ctl', '-d', subdev, '--set-ctrl=exposure=3000,analogue_gain=2048'])
        if grab('bright', 'frames-bright.raw') is None:
            return fail('bright capture is wedged')
        step('exposure-restore', ['v4l2-ctl', '-d', subdev, '--set-ctrl=exposure=1600,analogue_gain=128'])
    # Varied, non-fill data shows frames arrived. A person still has to look at
    # preview.ppm to say that it is the scene in front of the camera.
    result['complete'] = informative(scene) or informative(result.get('bright'))
    save()
    return result
