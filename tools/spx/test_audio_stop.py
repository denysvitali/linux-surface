#!/usr/bin/python3
"""Offline owner identity, targeted stop and guarded-return ordering tests."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import audio_stop
import trial


class Fixture(audio_stop.Live):
    def __init__(self, root):
        out, proc, lock = root/'out', root/'proc', root/'lock'
        out.mkdir(); (out/'audio').mkdir(); proc.mkdir(); lock.mkdir()
        (lock/'owner').write_text('audio-attempt')
        super().__init__(out, 'attempt', 'kernel', 'boot', root, 'dvitali', 1433, proc, lock)
        self.ready = dict(boot_id='boot', release='kernel', acoustic_passed=True,
            public_acoustic_passed=True, recording_closed=True, sink='spx_speakers',
            owner_pid=123, pcm_pid=124, peak_limit=1433, pa_gain=0)
        self.command = ['python3', '-B', str(root/'audio.py'), 'serve', '--owner',
            'audio-attempt', '--desktop-user', 'dvitali', '--desktop-peak', '1433',
            '--output', str(out/'audio')]
        for pid, comm, parent in ((123, 'python3', 1), (124, 'aplay', 123)):
            d=proc/str(pid); d.mkdir(); (d/'comm').write_text(comm)
            (d/'status').write_text(f'Uid: 0 0 0 0\nPPid: {parent}\n')
            (d/'stat').write_text(f'{pid} ({comm}) S '+ ' '.join(['0']*18+['999']))
            (d/'cmdline').write_bytes('\0'.join(self.command).encode()+b'\0')
        self.playback=proc/'asound/card0/pcm0p/sub0/status'
        self.capture=proc/'asound/card0/pcm1c/sub0/status'
        for p in (self.playback,self.capture): p.parent.mkdir(parents=True)
        self.playback.write_text('state: RUNNING\nowner_pid: 124\n')
        self.capture.write_text('closed'); self.write('serve-ready.json',self.ready)
    def boot_gate(self): pass
    def record(self,p): return json.loads(p.read_text())
    def write(self,n,r): (self.out/'audio'/n).write_text(json.dumps(r))
    def final(self):
        return dict(action='serve', success=True, before=dict(boot_id='boot',release='kernel'),
            serve=dict(self.ready,stopped=True,stop_reason='SIGTERM'),
            pcm=dict(pid=124,log='Playing raw data'),capture=dict(log='',error=None),
            desktop=dict(teardown=dict(passed=True),graph_restored=True),
            runtime_pm=dict(restored=True),parked=True,parked_state=dict(GPIO_VAL=0x18),recording_closed=True,
            cleanup_errors=[],background_errors=dict(capture=None,playback=[],desktop_monitor=[None]))
    def finished(self,result=None):
        for pid in (123,124): shutil.rmtree(self.proc/str(pid))
        shutil.rmtree(self.lock); self.playback.write_text('closed')
        self.write('serve-result.json',result or self.final())


class Stops(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.live=Fixture(Path(self.temp.name))
    def tearDown(self): self.temp.cleanup()
    def test_identity_refusals_never_signal(self):
        for case in ('boot','uid','argv','parent','pcm','capture','lock','peak'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                live=Fixture(Path(temp))
                if case=='boot': live.ready['boot_id']='old';live.write('serve-ready.json',live.ready)
                elif case=='uid': (live.proc/'123/status').write_text('Uid: 1000 1000 1000 1000\n')
                elif case=='argv': (live.proc/'123/cmdline').write_bytes(b'python3\0other.py\0serve\0')
                elif case=='parent': (live.proc/'124/status').write_text('PPid: 555\n')
                elif case=='pcm': live.playback.write_text('state: XRUN\nowner_pid: 124\n')
                elif case=='capture': live.capture.write_text('state: RUNNING')
                elif case=='lock': (live.lock/'owner').write_text('other')
                elif case=='peak': live.ready['peak_limit']=4000;live.write('serve-ready.json',live.ready)
                with patch('audio_stop.signal.pidfd_send_signal') as call:
                    with self.assertRaises(RuntimeError): audio_stop.exercise(live)
                    call.assert_not_called(); r=json.loads(live.target.read_text())
                    self.assertFalse(r['complete']);self.assertNotIn('signal',r)
    def test_targeted_once_signal_then_wrapper_wait(self):
        events=[]
        def pin(pid): events.append(('pin',pid));return {123:31,124:32}[pid]
        def stop(fd,sig): events.append(('signal',fd,sig));self.live.finished()
        with patch.object(self.live,'pin',side_effect=pin),patch('audio_stop.signal.pidfd_send_signal',side_effect=stop),patch('audio_stop.select.select',return_value=([31,32],[],[])):
            r=audio_stop.exercise(self.live)
        self.assertEqual(events,[('pin',123),('pin',124),('signal',31,signal.SIGTERM)])
        self.assertTrue(r['complete']);self.assertTrue(r['attached_teardown']);self.assertTrue(r['device_lock_released'])
    def test_identity_changes_after_pinning_refuse(self):
        def pin(pid):
            if pid==124:(self.live.proc/'124/stat').write_text('124 (aplay) S '+' '.join(['0']*18+['1001']))
            return pid
        with patch.object(self.live,'pin',side_effect=pin),patch('audio_stop.signal.pidfd_send_signal') as call:
            with self.assertRaisesRegex(RuntimeError,'identity changed'):audio_stop.exercise(self.live)
            call.assert_not_called()
    def test_final_partial_cleanup_or_xrun_refuses(self):
        original=self.live.final(); variants=[]
        for section,key,value in (('desktop','graph_restored',False),('runtime_pm','restored',False),('pcm','log','underrun!!!'),('serve','stop_reason','deadline'),('serve','pcm_pid',222)):
            r=deepcopy(original);r[section][key]=value;variants.append(r)
        r=deepcopy(original);r['desktop']['teardown']['passed']=False;variants.append(r)
        r=deepcopy(original);r['background_errors']['playback']=['failed'];variants.append(r)
        r=deepcopy(original);r['parked']=False;variants.append(r)
        self.live.finished()
        for r in variants:
            with self.subTest(result=r),self.assertRaises(RuntimeError):self.live.validate_final(r,dict(owner_pid=123,pcm_pid=124))
    def test_already_finished_deadline_requires_full_success(self):
        r=self.live.final();r['serve']['stop_reason']='deadline';self.live.finished(r)
        with patch('audio_stop.signal.pidfd_send_signal') as call:
            result=audio_stop.exercise(self.live);call.assert_not_called()
        self.assertTrue(result['already_stopped']);self.assertEqual(audio_stop.exercise(self.live),result)
    def test_failure_preserved_and_not_retried(self):
        self.live.capture.write_text('RUNNING')
        with self.assertRaises(RuntimeError):audio_stop.exercise(self.live)
        before=self.live.target.read_bytes();self.live.capture.write_text('closed')
        with patch('audio_stop.signal.pidfd_send_signal') as call:
            with self.assertRaises(RuntimeError):audio_stop.exercise(self.live)
            call.assert_not_called()
        self.assertEqual(self.live.target.read_bytes(),before)
    def test_no_audio_ignores_history(self):
        (self.live.out/'audio/serve-ready.json').unlink();self.live.finished(dict(error='historical'))
        with patch('audio_stop.signal.pidfd_send_signal') as call:
            r=audio_stop.exercise(self.live);call.assert_not_called()
        self.assertTrue(r['no_active_audio'])
    def test_startup_without_readiness_refuses(self):
        (self.live.out/'audio/serve-ready.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'starting or unfinished'):audio_stop.exercise(self.live)
    def test_pidfd_pin_detects_reuse(self):
        with patch.object(self.live,'start',side_effect=['1234','5678']),patch('audio_stop.os.pidfd_open',return_value=31),patch('audio_stop.os.close') as close:
            with self.assertRaisesRegex(RuntimeError,'PID changed'):self.live.pin(123)
            self.live.close();close.assert_called_once_with(31)
    def test_real_pidfd_owned_child_only(self):
        child=subprocess.Popen(['sleep','10']);sibling=subprocess.Popen(['sleep','10'])
        live=audio_stop.Live(Path('/unused'),'a','r','b',Path('/unused'),'dvitali',1433)
        try:
            fd=live.pin(child.pid);signal.pidfd_send_signal(fd,signal.SIGTERM)
            self.assertEqual(child.wait(timeout=2),-signal.SIGTERM);self.assertIsNone(sibling.poll())
        finally:
            live.close()
            if child.poll() is None:child.terminate();child.wait(timeout=2)
            sibling.terminate();sibling.wait(timeout=2)
    def return_fixture(self, failed):
        out=self.live.out
        for name,value in (('prepared.json',dict(preboot_id='old',release=__import__('os').uname().release)),
                           ('working-recovery.json',dict(entry='known',payload_sha256={}))):
            (out/name).write_text(json.dumps(value))
        paths={}
        for index,(name,text) in enumerate((('/proc/cmdline','spx_attempt=attempt spx_boot=mainline-functional'),
                 ('/proc/sys/kernel/random/boot_id','boot'),('/proc/uptime','500 500'),
                 ('/boot/grub/grub.cfg','known set default="spx-known-good"'))):
            target=out/str(index);target.write_text(text);paths[name]=target
        paths['/var/lib/spx-boot-diagnostics/functional']=out.parent
        # return uses parent / attempt; point that name to the fixture output.
        (out.parent/'attempt').symlink_to(out,target_is_directory=True)
        events=[]
        def stop(args):
            events.append('stop')
            if failed:raise RuntimeError('stop failed')
            return dict(complete=True)
        def output(args,**kwargs):
            return '' if args[0]=='efibootmgr' else 'saved_entry=spx-known-good\nnext_entry=\n'
        def run(args,**kwargs):
            events.append('reboot' if args==['systemctl','reboot'] else 'capture')
        with patch.object(trial,'ATTEMPT','attempt',create=True),patch.object(trial,'Path',side_effect=lambda path:paths.get(str(path),Path(path))),patch.object(trial,'stop_desktop_audio',side_effect=stop),patch.object(trial.subprocess,'check_output',side_effect=output),patch.object(trial.subprocess,'run',side_effect=run),patch.object(trial.os,'sync'):
            if failed:
                with self.assertRaisesRegex(RuntimeError,'stop failed'):trial.return_to_default(SimpleNamespace())
            else:trial.return_to_default(SimpleNamespace())
        return events
    def test_stop_failure_prevents_capture_and_reboot(self):
        self.assertEqual(self.return_fixture(True),['stop'])
        self.assertFalse((self.live.out/'return.json').exists())
    def test_stop_success_precedes_capture_and_reboot(self):
        self.assertEqual(self.return_fixture(False),['stop','capture','capture','reboot'])
        self.assertTrue(json.loads((self.live.out/'return.json').read_text())['audio_stop_complete'])


if __name__=='__main__':unittest.main()
