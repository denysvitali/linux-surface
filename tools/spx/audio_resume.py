#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Quiet retained playback, live default-client or idle stock-source AC resume."""
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import sys
import time
import traceback
from types import SimpleNamespace

import audio
import systemd_sleep as sleep


def admission(prepared, args):
    assert prepared.get('live_audio_resume') is True, 'live audio resume not prepared'
    for name in ('default_mic_resume', 'native_mic_resume'):
        assert type(prepared.get(name, False)) is bool and type(getattr(args, name, False)) is bool, name + ' must be boolean'
    assert prepared.get('native_mic_resume', False) == getattr(args, 'native_mic_resume', False), 'native microphone resume opt-in differs from preparation'
    assert not (getattr(args, 'native_mic_resume', False) and getattr(args, 'default_mic_resume', False)), 'microphone resume modes exclude each other'
    assert bool(prepared.get('default_mic_resume', False)) == bool(getattr(args, 'default_mic_resume', False)), 'default microphone resume opt-in differs from preparation'
    assert prepared.get('audio_mode') == 'parked'
    assert prepared.get('slim_s2idle_retain') is True and prepared.get('pmic_rtc') is True
    assert prepared.get('sensors_startup') is True
    assert not args.parked_audio and not args.verify_sleep_return
    assert args.allow_amp_power and args.allow_playback and args.allow_capture, 'explicit acoustic authorization required'
    assert args.desktop_peak == 1433 and not args.desktop_controls, 'quiet peak1433 only'


def process_identity(pid):
    text = (Path('/proc') / str(pid) / 'stat').read_text()
    return dict(pid=int(pid), start_ticks=text.rsplit(')', 1)[1].split()[19])


def owned_module(text, module_id):
    # pactl b096704c0 omits module indices from JSON; its text short
    # get_module_info_callback emits the actual index/name/argument columns.
    matches = []
    for line in text.splitlines():
        fields = line.split('\t', 3)
        # Replies may include unrelated nonnumeric diagnostics. Admit only
        # the actual module ID already owned by this source, never a substitute.
        if not fields[0].isdigit() or int(fields[0]) != int(module_id):
            continue
        assert len(fields) >= 3 and fields[2].strip(), 'Invalid owned Pulse module row'
        matches.append(dict(index=int(fields[0]), name=fields[1], argument=fields[2]))
    assert len(matches) == 1 and matches[0]['name'] == 'module-pipe-source', 'Owned microphone module missing'
    return matches[0]


def source_admission(source, report):
    fields = ('index', 'name', 'owner_module', 'sample_specification',
              'channel_map', 'monitor_source', 'volume', 'mute')
    metadata = {key: source[key] for key in fields if key in source}
    # Preserve the owned endpoint observation even when admission rejects it.
    report['source_admission'] = metadata
    # DZ's silent real PipeWire/Pulse fixture reports the empty STRING for a
    # pipe source; require its presence, not an absent key or inferred null.
    assert 'monitor_source' in source and isinstance(source['monitor_source'], str) and source['monitor_source'] == '', 'Default microphone is a sink monitor or lacks the observed non-monitor sentinel'
    assert source.get('sample_specification') == 's16le 1ch 48000Hz' and source.get('channel_map') == 'mono', 'Default microphone source geometry changed'
    return metadata


class DefaultMicrophone:
    """One public default client, scored from the existing quiet speaker tones."""
    def __init__(self, graph, capture, report, pcm=None):
        self.graph, self.capture, self.pcm = graph, capture, pcm
        self.report = report
        self.client = self.source = None
        self.name = 'spx-default-microphone-resume-' + str(audio.os.getpid())
        self.reference = None
        self.closed = False

    def start(self):
        self.report.update(passed=False, phases=[], raw_recording=None,
                           explicit_device=False, maximum_wall_seconds=120)
        assert self.capture.wall_deadline <= self.capture.started_boottime + 120
        self.source = self.graph.microphone = audio.DesktopMicSource(
            self.graph, self.capture, self.report,
            self.graph.default_source_before_test)
        self.source.start()
        self.client = audio.DesktopRecording(self.graph, self.name,
            maximum_seconds=120, wall_deadline=self.capture.wall_deadline)
        self.report['wall_deadline_boottime'] = self.capture.wall_deadline
        deadline = time.monotonic() + 5
        while not self.source.require_client_route(self.name):
            self.client.healthy()
            self.source.healthy()
            assert time.monotonic() < deadline, 'Default microphone client did not attach'
            time.sleep(.05)
        self.source.forward = True
        # Keep consuming in this same client through the sleep. Native capture
        # remains the only hardware owner and supplies the bounded wall fence.
        self.client.wait_frames(48000)
        self.report['held'] = self.identity()

    def identity(self):
        self.client.healthy()
        self.source.healthy()
        assert self.graph.run('pactl', 'get-default-source') == self.source.name, 'Default microphone changed'
        sources = json.loads(self.graph.run('pactl', '--format=json', 'list', 'sources'))
        owned = [item for item in sources if item['name'] == self.source.name]
        assert len(owned) == 1, 'Owned default microphone source missing'
        source = owned[0]
        metadata = source_admission(source, self.report)
        assert str(source['index']) == str(self.source.source_id), 'Default microphone source index changed'
        assert str(source['owner_module']) == str(self.source.module), 'Default microphone module changed'
        module = owned_module(self.graph.run('pactl', '--format=text', 'list', 'short', 'modules'),
                              self.source.module)
        outputs = json.loads(self.graph.run('pactl', '--format=json', 'list', 'source-outputs'))
        routed = [item for item in outputs if str(item['source']) == str(self.source.source_id)]
        assert len(routed) == 1 and routed[0].get('properties', {}).get('application.name') == self.name, 'Unexpected default microphone recording client'
        output = routed[0]
        assert not output.get('corked', False), 'Default recording client is corked'
        props = output.get('properties', {})
        client_pid = props.get('application.process.id')
        assert str(client_pid).isdigit(), 'Default recording process identity missing'
        units = ('pipewire.service', 'pipewire-pulse.service', 'wireplumber.service')
        text = self.graph.run('systemctl', '--user', 'show',
            '--property=Id,ActiveState,SubState,MainPID,ExecMainStartTimestampMonotonic', '--', *units)
        services = {}
        for block in text.split('\n\n'):
            values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            assert values.get('ActiveState') == 'active' and values.get('SubState') == 'running', 'Desktop audio service not running'
            services[values['Id']] = dict(identity=process_identity(values['MainPID']),
                started=values['ExecMainStartTimestampMonotonic'])
        assert set(services) == set(units), 'Desktop service identity missing'
        native = {} if self.pcm is None else {name: process_identity(owner.process.pid)
            for name, owner in (('playback', self.pcm), ('capture', self.capture))}
        return dict(native_processes=native, owner=process_identity(self.client.process.pid),
            recording_process=process_identity(client_pid), services=services,
            source=metadata,
            module=module,
            source_output={key: output.get(key) for key in ('index', 'source', 'client')})

    def retained(self):
        after = self.identity()
        assert after == self.report['held'], 'Default microphone source/client/service identity changed'
        self.report.update(after=after, same_owners=True)

    def begin_suspend(self, seconds=60):
        self.client.healthy()
        self.report['forwarding_pause'] = self.source.pause_forwarding(seconds)
        self.report['forwarding_pause']['client_frame'] = self.client.mark()

    def end_suspend(self):
        self.client.healthy()
        self.report['forwarding_resume'] = self.source.resume_forwarding()
        begin = self.client.mark()
        self.client.wait_frames(begin + 4800)
        self.report['forwarding_resume'].update(client_frame_before=begin,
                                               client_frame_after=self.client.mark())

    def reference_begin(self):
        self.client.healthy()
        self.reference_start = self.client.mark()

    def reference_end(self):
        self.client.wait_frames(self.reference_start + 2 * 48000)
        end = self.client.mark()
        self.reference = self.client.samples(end - 2 * 48000, end)
        self.reference_frames = (end - 2 * 48000, end)

    def tone_begin(self):
        assert self.reference is not None, 'Default microphone fresh reference missing'
        self.tone_start = self.client.mark()

    def tone_end(self):
        from acoustic import score_phase
        self.client.wait_frames(self.tone_start + 3 * 48000)
        end = self.client.mark()
        phase = dict(reference_start_frame=self.reference_frames[0],
                     reference_end_frame=self.reference_frames[1],
                     start_frame=self.tone_start, end_frame=end,
                     score=score_phase(self.client.samples(self.tone_start, end), self.reference, [440, 660]))
        self.report['phases'].append(phase)
        self.reference = None
        assert phase['score']['passed'], 'Default microphone client acoustic proof failed: ' + phase['score']['reason']
        self.source.healthy()

    def close(self):
        if self.closed:
            return
        errors = []
        if self.source is not None:
            self.source.forward = False
        try:
            if self.client is not None:
                self.client.close()
                assert self.client.process.poll() is not None, 'Default recording client remains active'
                self.report['client_closed'] = True
        except Exception as error:
            errors.append(str(error))
        try:
            if self.source is not None:
                self.source.close()  # Unload, then restore the exact configured preference.
                assert not self.source.report.get('adapter_error'), 'Default microphone adapter failed'
                self.report['default_source_restored'] = self.source.report.get('restored') is True
        except Exception as error:
            errors.append(str(error))
        finally:
            self.graph.microphone = None
            self.closed = True
            self.reference = None
            self.report['cleanup_errors'] = errors
        assert not errors, 'Default microphone cleanup failed: ' + '; '.join(errors)


class ResumeWindow:
    def __init__(self, ops, result, default_mic=False):
        self.ops, self.result, self.default_mic = ops, result, default_mic
        self.microphone = None

    def prepare(self, graph, capture, pcm):
        if self.default_mic:
            self.microphone = DefaultMicrophone(graph, capture,
                self.result.setdefault('default_microphone', {}), pcm)
            graph.live_resume_microphone = self.microphone
            try:
                self.microphone.start()
            except Exception:
                # Unwind the public client/source before initialize can close
                # native consumers; preserve the original admission failure.
                try:
                    self.microphone.close()
                except Exception as error:
                    self.result['default_microphone_start_cleanup_error'] = str(error)
                raise

    def __call__(self, *arguments):
        try:
            retained_window(self.ops, self.result, *arguments, microphone=self.microphone)
        finally:
            if self.microphone is not None:
                passed = self.result.get('functional_pass', False)
                self.result['functional_pass'] = False
                failed = sys.exc_info()[0] is not None
                try:
                    self.microphone.close()
                except Exception as error:
                    if not failed:
                        raise
                    self.result['default_microphone_window_cleanup_error'] = str(error)
                self.result['functional_pass'] = bool(passed and
                    self.microphone.report.get('client_closed') and
                    self.microphone.report.get('default_source_restored') and
                    not self.microphone.report.get('cleanup_errors'))


def sound_fds(pid):
    result = {}
    for fd in (Path('/proc') / str(pid) / 'fd').iterdir():
        target = fd.readlink().as_posix()
        if target.startswith('/dev/snd/'):
            result[fd.name] = target
    assert result, 'native audio file descriptors missing'
    return result


class LiveOwnedAudio:
    """Observe only this runner's initialized live owners, never relax parked checks."""
    def __init__(self, lease, pcm, graph, capture, paths, mapping):
        self.lease, self.pcm, self.graph, self.capture = lease, pcm, graph, capture
        self.paths, self.mapping = paths, mapping
        self.report = dict(powered_retention=True, energy_saving_claim=False,
                           playback_or_capture_opened=True, same_native_owners=False)
        self.report['held'] = self.check()

    def check(self):
        self.pcm.healthy()
        self.capture.healthy()
        self.graph.monitor.healthy()
        self.graph.require_public_idle()
        assert self.pcm.source is None and not self.graph.monitor.forward, 'local digital silence required'
        assert self.graph.monitor.blocks.empty(), 'public monitor queue not drained'
        assert audio.read_text(self.lease.control) == 'on'
        assert audio.read_text(self.lease.master / 'power/runtime_status') == 'active'
        stereo = audio.check_stereo(self.mapping, self.paths, initialized=True)
        processes = dict(playback=self.pcm.process.pid, capture=self.capture.process.pid,
                         monitor=self.graph.monitor.process.pid)
        statuses = {}
        geometry = {}
        for name, owner in (('playback', self.pcm), ('capture', self.capture)):
            text = audio.read_text(owner.status)
            assert re.search(r'^state:\s+RUNNING$', text, re.M), name + ' not running'
            assert re.search(r'^owner_pid\s*:\s*' + str(owner.process.pid) + r'$', text, re.M), name + ' owner changed'
            statuses[name] = dict(pid=owner.process.pid, state='RUNNING', fds=sound_fds(owner.process.pid))
            geometry[name] = audio.read_text(owner.status.parent / 'hw_params')
        # No unrelated native consumer may appear in this owned sleep window.
        owned = {self.pcm.status, self.capture.status}
        for path in Path('/proc/asound').glob('card*/pcm*/sub*/status'):
            if path not in owned:
                assert audio.read_text(path) == 'closed', 'unowned audio consumer appeared'
        return dict(processes=processes, native_owners=statuses, geometry=geometry,
                    initialized_counts={str(unit): state['LATE_INIT_COUNT']
                                        for unit, state in stereo['codec_shadows'].items()},
                    stereo=stereo, digital_zero=True)

    def retained(self, before):
        after = self.check()
        for name in ('processes', 'native_owners', 'geometry', 'initialized_counts'):
            assert after[name] == before[name], name + ' changed across suspend'
        self.report['same_native_owners'] = True
        self.report['after'] = after
        return after


def require_native_idle(source, graph):
    """Do not renew a deadline while any preceding consumer lives."""
    assert source.active_owner is None, 'Native recording owner still active'
    assert source.thread is None or not source.thread.is_alive(), 'Native watchdog still active'
    for client in getattr(graph, 'recordings', []):
        assert client.process.poll() is not None, 'Prior default client not reaped'
        assert not client.thread.is_alive(), 'Prior default reader still active'
        assert client.log.closed and not client.raw, 'Prior recording not closed/discarded'
    source.require_closed('idle-phase-boundary')
    assert audio.read_text(source.status) == 'closed', 'Native capture remains open'


class NativeIdleAudio(LiveOwnedAudio):
    """Retained playback and idle stock source; no recording during sleep."""
    def __init__(self, lease, pcm, graph, source, paths, mapping, mixer_controls):
        self.lease, self.pcm, self.graph, self.source = lease, pcm, graph, source
        self.paths, self.mapping, self.mixer_controls = paths, mapping, mixer_controls
        self.report = dict(powered_retention=True, energy_saving_claim=False,
                           playback_or_capture_opened=True, same_native_owners=False,
                           capture_closed_during_sleep=True)
        self.report['held'] = self.check()

    def check(self):
        self.source.serve_healthy()
        require_native_idle(self.source, self.graph)
        endpoint = self.source.endpoint()
        assert endpoint.get('state') in ('IDLE', 'SUSPENDED'), 'Native source active during sleep window'
        outputs = json.loads(self.graph.run('pactl', '--format=json', 'list', 'source-outputs'))
        assert not any(str(row.get('source')) == str(self.source.source_id) for row in outputs), 'Recording client appeared in idle window'
        assert self.graph.run('pactl', 'get-default-source') == self.source.name, 'Native default microphone changed'
        self.pcm.healthy()
        self.graph.monitor.healthy()
        self.graph.require_public_idle()
        assert self.pcm.source is None and not self.graph.monitor.forward, 'local digital silence required'
        assert self.graph.monitor.blocks.empty(), 'public monitor queue not drained'
        assert audio.read_text(self.lease.control) == 'on'
        assert audio.read_text(self.lease.master / 'power/runtime_status') == 'active'
        status = audio.read_text(self.pcm.status)
        assert re.search(r'^state:\s+RUNNING$', status, re.M), 'playback not running'
        assert re.search(r'^owner_pid\s*:\s*' + str(self.pcm.process.pid) + r'$', status, re.M), 'playback owner changed'
        trigger = re.search(r'^trigger_time\s*:\s*(.+)$', status, re.M)
        assert trigger, 'playback trigger missing'
        for path in Path('/proc/asound').glob('card*/pcm*/sub*/status'):
            if path != self.pcm.status:
                assert audio.read_text(path) == 'closed', 'unowned audio consumer appeared'
        stereo = audio.check_stereo(self.mapping, self.paths, initialized=True)
        controls = {}
        for control in self.mixer_controls:
            controls[control] = audio.subprocess.run(['amixer', '-c', str(self.source.card),
                'cget', 'name=' + control], check=True, capture_output=True, text=True, timeout=2).stdout
        return dict(processes={name: process_identity(owner.process.pid) for name, owner in
                              (('playback', self.pcm), ('monitor', self.graph.monitor))},
                    native_owners=dict(playback=dict(pid=self.pcm.process.pid, state='RUNNING',
                        trigger_time=trigger[1], fds=sound_fds(self.pcm.process.pid))),
                    geometry=dict(playback=audio.read_text(self.pcm.status.with_name('hw_params'))),
                    initialized_counts={str(unit): state['LATE_INIT_COUNT']
                                        for unit, state in stereo['codec_shadows'].items()},
                    native_source=dict(source={key: endpoint.get(key) for key in
                        ('index', 'name', 'owner_module', 'sample_specification', 'channel_map', 'monitor_source', 'volume', 'mute')},
                        module=dict(self.source.module_row), services=self.source.services,
                        configured_default=audio.configured_default_source(self.graph), mixers=controls),
                    capture_status='closed', stereo=stereo, digital_zero=True)

    def retained(self, before):
        after = super().retained(before)
        assert after['native_source'] == before['native_source'], 'native source/default/services/mixers changed across suspend'
        return after


class NativeResumeWindow:
    """Close the oracle, retain one source idle, then open fresh default clients."""
    after_recording = True

    def __init__(self, ops, result):
        self.ops, self.result = ops, result
        self.source = None

    def phase(self, name, graph, pcm, paths, mapping):
        require_native_idle(self.source, graph)
        started = time.clock_gettime(time.CLOCK_BOOTTIME)
        self.source.wall_deadline = started + 60
        evidence = self.result['native_microphone'][name] = dict(clients=[], recording=None,
            maximum_seconds=60, started_boottime=started, wall_deadline_boottime=started + 60,
            frequencies_hz=[440, 660], microphone_client_passed=False)
        previous_trigger = (self.result['native_microphone']['pre']['clients'][-1]['native_owner']['trigger_time']
                            if name == 'post' else None)
        audio.verify_native_microphone_clients(self.source, graph, evidence, pcm, paths, mapping,
                                               frequencies=(440, 660), previous_trigger=previous_trigger)
        require_native_idle(self.source, graph)
        evidence['closed_boottime'] = time.clock_gettime(time.CLOCK_BOOTTIME)
        assert evidence['closed_boottime'] < self.source.wall_deadline, 'Native phase exceeded60s'
        assert evidence['microphone_client_passed'] and len(evidence['clients']) == 2
        assert all(row['passed'] for row in evidence['clients']), 'Native client proof incomplete'

    def __call__(self, report, pcm, graph, capture, paths, mapping):
        result = self.result
        result['pre_playback'] = report.pop('public_desktop')
        evidence = result['native_microphone'] = dict(passed=False, recording=None,
            scope='same idle stock source across normal30s AC sleep; fresh default clients')
        assert report.get('recording_closed') and capture.process.poll() is not None, 'Original oracle must close before native source load'
        assert audio.read_text(capture.status) == 'closed', 'Original oracle PCM remains open'
        self.source = graph.microphone = audio.NativeMicSource(graph, capture.card,
            evidence.setdefault('source', {}), time.clock_gettime(time.CLOCK_BOOTTIME) + 60,
            graph.default_source_before_test, desktop=True)
        try:
            self.source.start()
            assert self.source.default_selected, 'Stock microphone is not the ordinary default source'
            self.phase('pre', graph, pcm, paths, mapping)
            quiet(pcm, graph)
            contract = NativeIdleAudio(self.ops.audio, pcm, graph, self.source, paths, mapping,
                [row['name'] for row in report['microphone_mixer']])
            self.ops.audio = contract
            result['live_audio'] = contract.report
            result['phase'] = 'idle-native-source-before-normal-suspend'
            self.ops.save(result)
            graph.monitor.begin_suspend(60)
            try:
                self.ops.inhibit_idle()
                self.ops.open_shadows()
                result['sleep'] = self.ops.sleep()
                assert sleep.sleep_proven(result['sleep']), 'normal-service/RTC/kernel/thaw proof incomplete'
            finally:
                failed = sys.exc_info()[0] is not None
                try:
                    graph.monitor.end_suspend()
                except Exception as error:
                    if not failed:
                        raise
                    result['monitor_window_cleanup_error'] = str(error)
            # Reject source/service/default/playback changes before recording.
            contract.retained(contract.report['held'])
            self.phase('post', graph, pcm, paths, mapping)
            clients = evidence['pre']['clients'] + evidence['post']['clients']
            assert len({row['pid'] for row in clients}) == 4, 'Fresh pre/post ordinary clients required'
            before_trigger = evidence['pre']['clients'][-1]['native_owner']['trigger_time']
            after_trigger = evidence['post']['clients'][0]['native_owner']['trigger_time']
            assert before_trigger != after_trigger, 'First post-sleep client did not restart native capture'
            quiet(pcm, graph)
            contract.retained(contract.report['held'])
            evidence.update(passed=True, same_source=True, fresh_post_clients=True, new_post_capture_trigger=True)
            result['functional_pass'] = bool(result['pre_playback']['acoustic_passed'])
        finally:
            failed = sys.exc_info()[0] is not None
            passed = result.pop('functional_pass', False)
            try:
                self.source.close()  # Unload before mixer/playback teardown.
                assert self.source.report.get('restored') and not self.source.report.get('adapter_error'), 'Native source cleanup failed'
                graph.microphone = None
                quiet(pcm, graph)
                graph.monitor.close()
                graph.monitor = None
                result['functional_pass'] = passed
            except Exception as error:
                if not failed:
                    raise
                result['native_microphone_cleanup_error'] = str(error)


def quiet(pcm, graph):
    graph.require_public_idle()
    graph.monitor.forward = False
    pcm.set_source(None)
    pcm.settle(.8)  # Drain pipe/ALSA ring before the freeze window.
    while True:
        try:
            graph.monitor.blocks.get_nowait()
        except queue.Empty:
            break
    graph.monitor.healthy()


def retained_window(ops, result, report, pcm, graph, capture, paths, mapping, *, microphone=None):
    result['pre_playback'] = report.pop('public_desktop')
    quiet(pcm, graph)
    if microphone is not None:
        microphone.retained()
        assert len(microphone.report['phases']) == 1, 'Default microphone pre-sleep proof missing'
    contract = LiveOwnedAudio(ops.audio, pcm, graph, capture, paths, mapping)
    ops.audio = contract
    result['live_audio'] = contract.report
    # The infrastructure snapshot was taken before PCM open. Replace only its
    # separate audio observation with the strict live-owner contract.
    if microphone is None:
        result['before']['parked_audio'] = contract.report['held']
    # The default-client test keeps the original parked baseline for its
    # deferred infrastructure checks; live identities stay in live_audio.
    result['phase'] = 'owned-live-audio-before-normal-suspend'
    ops.save(result)
    graph.monitor.begin_suspend(60)
    try:
        if microphone is not None:
            microphone.begin_suspend(60)
        ops.inhibit_idle()
        ops.open_shadows()
        result['sleep'] = ops.sleep()
        assert sleep.sleep_proven(result['sleep']), 'normal-service/RTC/kernel/thaw proof incomplete'
        if microphone is not None:
            microphone.end_suspend()
    finally:
        failed = sys.exc_info()[0] is not None
        try:
            graph.monitor.end_suspend()
        except Exception as error:
            if not failed:
                raise
            result['monitor_window_cleanup_error'] = str(error)
    if microphone is None:
        result['after'] = ops.post(result['before'])
    contract.retained(contract.report['held'])
    if microphone is not None:
        microphone.retained()
    # Fresh reference and fixed two tones, using the SAME monitor and native
    # playback/capture descriptors. No connect_public, initialize or reopen.
    audio.verify_public_playback(report, pcm, graph, capture, 1433, connected=True, microphone=microphone)
    result['post_playback'] = report.pop('public_desktop')
    quiet(pcm, graph)
    contract.retained(contract.report['held'])
    result['functional_pass'] = bool(result['pre_playback']['acoustic_passed'] and
                                     result['post_playback']['acoustic_passed'])
    if microphone is not None:
        microphone.retained()
        microphone.report['passed'] = bool(len(microphone.report['phases']) == 2 and
            all(phase['score']['passed'] for phase in microphone.report['phases']) and
            microphone.report.get('same_owners'))
        result['functional_pass'] = result['functional_pass'] and microphone.report['passed']


def exercise(ops, args, owner):
    result = dict(complete=False, scope='same public playback and native capture owners across one normal30s AC s2idle',
                  audio_tested=True, audio_mode='live-retention', full_suspend_acceptance=False,
                  default_mic_resume=bool(getattr(args, 'default_mic_resume', False)),
                  native_mic_resume=bool(getattr(args, 'native_mic_resume', False)))
    if result['default_mic_resume']:
        result['scope'] = 'same ordinary default-source recording client and native audio owners across one normal30s AC s2idle'
    if result['native_mic_resume']:
        result['scope'] = 'same idle stock default microphone across one normal30s AC s2idle; fresh ordinary pre/post clients'
    lease = None
    report = dict(utc=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
                  remaining_prerequisites=list(audio.UNMET))
    result['audio'] = report
    try:
        admission(json.loads((ops.output.parent / 'prepared.json').read_text()), args)
        result['before'] = ops.gate()
        ops.save(result)
        result['direct_prerequisite'] = ops.direct()  # Still no PCM open.
        ops.gate()
        lease = ops.audio
        configured = SimpleNamespace(action='serve', desktop_peak=1433, desktop_controls=False,
                                     allow_amp_power=True, allow_playback=True, allow_capture=True,
                                     owner=owner, desktop_user=args.desktop_user, output=ops.output,
                                     microphone_source='DMIC1', microphone_array=False,
                                     capture_reopen=False, capture_contract_check=False,
                                     default_mic_resume=result['default_mic_resume'],
                                     native_mic_resume=result['native_mic_resume'])
        audio.initialize(configured, report,
            live_resume=(NativeResumeWindow(ops, result) if result['native_mic_resume'] else
                         ResumeWindow(ops, result, result['default_mic_resume'])))
        assert result.get('functional_pass'), 'pre/post acoustic proof incomplete'
        assert not report['capture_deadline_expired'], 'capture deadline expired'
        assert report['capture']['recording'] is None and report['capture']['closed_status'] == 'closed'
        assert report['capture']['ownership_wall_seconds'] <= (90 if result['native_mic_resume'] else 120), 'microphone ownership exceeded bounded wall cap'
        if result['native_mic_resume']:
            assert result['native_microphone']['passed'] and result['native_microphone']['source']['restored']
        if result['default_mic_resume']:
            assert result['default_microphone']['client_closed'] and result['default_microphone']['default_source_restored']
        assert report['parked'] and report['runtime_pm']['restored']
        for name in ('pcm', 'capture'):
            assert not re.search(r'underrun|overrun|error|reprepare|recovering', report[name].get('log', ''), re.I), name + ' recovery/error'
        if result['default_mic_resume'] or result['native_mic_resume']:
            # initialize has closed both hardware PCMs, parked amplifiers and
            # restored graph/mixer state. Only now spend time on WLAN/streams.
            ops.audio = lease
            result['after'] = ops.post(result['before'])
            result['post_infrastructure_passed'] = True
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        result['traceback'] = traceback.format_exc()
        if hasattr(ops, 'sleep_result'):
            result['sleep'] = ops.sleep_result
    finally:
        # initialize has attempted park/close on every path. Only now can the
        # original parked lease enforce closed PCMs, FIFO/ports and restore PM.
        if lease is not None:
            ops.audio = lease
        try:
            result['cleanup'] = ops.cleanup()
        except Exception as error:
            result['cleanup_error'] = str(error)
        result['complete'] = bool(result.get('functional_pass') and not result.get('error') and
                                  not result.get('cleanup_error') and
                                  result.get('cleanup', {}).get('masks_restored') and
                                  not report.get('cleanup_errors') and
                                  (not (result['default_mic_resume'] or result['native_mic_resume']) or
                                   result.get('post_infrastructure_passed') is True))
        ops.save(result)
    return result
