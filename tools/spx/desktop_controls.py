"""Bounded, uncalibrated software volume/mute checks; never retain raw audio."""
import json
import math
import os
import re
import signal
import threading
import time

from acoustic import _measure, score_phase


FREQUENCIES = (440, 660)
REDUCED_VOLUME = 52016  # Pulse cubic volume: approximately half linear amplitude.


def coherent_maxima(samples, rate=48000):
    """Maximum across every 0.4 s window/0.1 s step, including brief leakage."""
    step = round(rate * 0.1)
    window = 4 * step
    if len(samples) < window:
        raise ValueError('Muted phase needs at least 0.4 seconds')
    measured = [_measure(samples[start:start + window], FREQUENCIES, rate)[0]
                for start in range(0, len(samples) - window + 1, step)]
    return {str(hz): max(item[hz] for item in measured) for hz in FREQUENCIES}


def score_controls(original, reduced, restored, muted_samples, muted_reference,
                   digital, rate=48000):
    """Engineered thresholds; no calibrated loudness or physical balance claim."""
    result = dict(passed=False, reasons=[], targets={}, muted_maxima={},
                  reduced_db_range=[-9, -3], restored_db_range=[-3, 3],
                  minimum_mute_suppression_db=20, digital=dict(digital))
    for name, scored in (('original', original), ('reduced', reduced), ('restored', restored)):
        if not scored.get('passed'):
            result['reasons'].append(name + ' audible acoustic phase failed')
    if result['reasons']:
        return result
    maxima = coherent_maxima(muted_samples, rate)
    quiet = coherent_maxima(muted_reference, rate)
    result['muted_maxima'] = maxima
    if digital.get('frames', 0) < 2 * rate or digital.get('input_peak', 2) > 1 or digital.get('output_peak', 2) > 1:
        result['reasons'].append('Mute monitor was nonzero or did not cover the stimulus')
    for hz in FREQUENCIES:
        key = str(hz)
        levels = {name: scored['targets'][key]['rms']
                  for name, scored in (('original', original), ('reduced', reduced), ('restored', restored))}
        def ratio(value, reference):
            return 20 * math.log10(max(value, 1e-9) / max(reference, 1e-9))
        item = result['targets'][key] = dict(levels)
        item.update(reduced_to_original_db=ratio(levels['reduced'], levels['original']),
                    reduced_to_restored_db=ratio(levels['reduced'], levels['restored']),
                    restored_to_original_db=ratio(levels['restored'], levels['original']),
                    muted_rms=maxima[key], quiet_rms=quiet[key])
        for target in ('reduced_to_original_db', 'reduced_to_restored_db'):
            if not -9 <= item[target] <= -3:
                result['reasons'].append(f'{hz} Hz reduction outside -9..-3 dB')
        if not -3 <= item['restored_to_original_db'] <= 3:
            result['reasons'].append(f'{hz} Hz unity restoration outside +/-3 dB')
        # Measurement floor and the entire predeclared quiet reference must
        # support the 20 dB claim. A failed audible score alone never proves mute.
        leakage = max(0.1, quiet[key], maxima[key])
        for name in ('original', 'restored'):
            item['mute_to_' + name + '_db'] = ratio(leakage, levels[name])
            if item['mute_to_' + name + '_db'] > -20:
                result['reasons'].append(f'{hz} Hz mute suppression insufficient or noise-floor inconclusive')
    result['passed'] = not result['reasons']
    return result


def native_identity(status, pid, need):
    fields = {}
    for name in ('state', 'owner_pid', 'trigger_time'):
        match = re.search(r'^' + name + r'\s*:\s*(\S+)', status, re.M)
        need(match is not None, 'Native status is missing ' + name)
        fields[name] = match.group(1)
    need(fields['state'] == 'RUNNING' and fields['owner_pid'] == str(pid),
         'Native stream state or owner changed')
    return fields


def read_controls(graph, volume, muted, need):
    need(graph.run('pactl', 'get-default-sink') == 'spx_speakers', 'Default sink changed')
    sinks = json.loads(graph.run('pactl', '--format=json', 'list', 'sinks'))
    sink = next((s for s in sinks if s['name'] == 'spx_speakers'), None)
    need(sink is not None, 'Public sink disappeared')
    values = sink.get('volume', {})
    need(set(values) == {'front-left', 'front-right'} and
         all(v['value'] == volume for v in values.values()) and sink['mute'] is muted,
         'Actual public volume or mute differs from requested controls')
    objects = json.loads(graph.run('pw-dump'))
    nodes = [o['info']['props'] for o in objects if o.get('type') == 'PipeWire:Interface:Node'
             and o.get('info', {}).get('props', {}).get('node.name') == 'spx_speakers']
    need(len(nodes) == 1 and nodes[0].get('monitor.channel-volumes') in (True, 'true'),
         'Public monitor must include channel volume and mute')
    return dict(volume=[v['value'] for v in values.values()], mute=sink['mute'],
                monitor_channel_volumes=True)


def verify_controls(report, pcm, graph, capture, tone, need):
    evidence = report['desktop_controls'] = dict(passed=False, maximum_seconds=60,
        deadline_expired=False, phases={}, pcm_pid=pcm.process.pid,
        capture_pid=capture.process.pid, settled_interval_seconds=[0.4, 4.0],
        scope='bounded software volume, mute and restoration; no listening-quality claim')
    started = time.monotonic()
    original = report['public_desktop']['score']
    samples = {}
    references = {}
    original_pcm = pcm.process
    original_capture = capture.process
    baseline_pcm = native_identity(pcm.healthy(), pcm.process.pid, need)
    baseline_capture = native_identity(capture.status.read_text(), capture.process.pid, need)
    evidence['native_before'] = dict(playback=baseline_pcm, capture=baseline_capture)

    def expire():
        evidence['deadline_expired'] = True
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(60, expire)
    timer.start()
    try:
        for name, volume, muted in (('reduced', REDUCED_VOLUME, False),
                                    ('muted', 65536, True), ('restored', 65536, False)):
            graph.require_public_idle()
            graph.monitor.forward = False
            pcm.settle(0.5)
            graph.run('pactl', 'set-sink-volume', 'spx_speakers', str(volume))
            graph.run('pactl', 'set-sink-mute', 'spx_speakers', str(int(muted)))
            item = evidence['phases'][name] = read_controls(graph, volume, muted, need)
            graph.monitor.begin_phase()
            quiet_begin = capture.mark()
            pcm.settle(2)
            capture.wait_frames(quiet_begin + 2 * 48000)
            quiet_end = capture.mark()
            references[name] = capture.samples(quiet_end - 2 * 48000, quiet_end)
            item['quiet_frames'] = [quiet_end - 2 * 48000, quiet_end]
            quiet_monitor = graph.monitor.phase_snapshot()
            need(quiet_monitor['input_peak'] <= 1, 'Public reference was not digitally silent')
            graph.require_public_idle()
            begin = capture.mark()
            graph.monitor.begin_phase()
            graph.play(tone({0, 1}, amplitude=32767), 'controls-' + name, default_sink=True)
            pcm.settle(0.8)
            capture.wait_frames(begin + 4 * 48000)
            graph.require_public_idle()
            item['after_playback_controls'] = read_controls(graph, volume, muted, need)
            graph.monitor.forward = False
            pcm.settle(0.5)  # Empty monitor/ALSA queues before CPU-bound scoring.
            item['monitor'] = graph.monitor.phase_snapshot()
            item['signal_frames'] = [begin + round(0.4 * 48000), begin + 4 * 48000]
            samples[name] = capture.samples(*item['signal_frames'])
            item['pcm_status'] = pcm.healthy()
            item['native_identity'] = dict(
                playback=native_identity(item['pcm_status'], pcm.process.pid, need),
                capture=native_identity(capture.status.read_text(), capture.process.pid, need))
            need(item['native_identity'] == evidence['native_before'],
                 'Native PCM/capture owner or trigger identity changed')
            graph.monitor.healthy()
            capture.healthy()
            need(pcm.process is original_pcm and capture.process is original_capture,
                 'Native PCM/capture lifetime changed during controls')
            need(pcm.feed_stats['inserted_gap_events'] == 0, 'Playback feed inserted gaps')
            if not muted:
                item['score'] = score_phase(samples[name], references[name], list(FREQUENCIES))
                need(item['score']['passed'], 'Controls audible acoustic phase failed: ' + item['score']['reason'])
            else:
                # Compute while ALSA consumes local silence; raw data lives only
                # in the already bounded capture and these transient arrays.
                item['coherent_maxima'] = coherent_maxima(samples[name])
        evidence['score'] = score_controls(original, evidence['phases']['reduced']['score'],
            evidence['phases']['restored']['score'], samples['muted'], references['muted'],
            evidence['phases']['muted']['monitor'])
        need(evidence['score']['passed'], '; '.join(evidence['score']['reasons']))
        read_controls(graph, 65536, False, need)
        evidence['passed'] = True
    finally:
        timer.cancel()
        samples.clear()
        references.clear()
        graph.monitor.forward = False
        evidence['seconds'] = time.monotonic() - started
        # Outer graph.close restores the user's prior preferences on all exits.
        # Successful serve handoff keeps unity/unmuted as before this opt-in.
