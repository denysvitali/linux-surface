#!/usr/bin/python3
"""Independently verify Y's bounded, moderate-level PCM follow-up archive."""

import hashlib
import json
import os
import struct
from pathlib import Path

os.umask(0o077)
Y = Path('/var/lib/spx-boot-diagnostics/attempts/20260927y')
OUT = Y / 'moderate-tone-test'
BID = 'b5f0a540-3e81-4415-b08c-f869e01349a2'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


assert os.geteuid() == 0 and not (Y / 'independent-moderate-tone-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
expected = json.loads((OUT / 'sha256.json').read_text())
actual = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()
          and p.name != 'sha256.json'}
assert actual == expected
report = json.loads((OUT / 'report.json').read_text())
assert report['boot_id'] == BID and report['aplay_exit_code'] == 0
assert report['rate_hz'] == 48000 and report['samples_per_channel'] == 48000
assert all(value == 0 for value in report['kernel_delta_markers'].values())
signal = (OUT / 'signal.s16le').read_bytes()
assert len(signal) == 48000 * 4 and sha(OUT / 'signal.s16le') == report['signal_sha256']
samples = list(struct.iter_unpack('<hh', signal))
left = [sample[0] for sample in samples]
assert all(sample[1] == 0 for sample in samples)
assert max(left) <= 4000 and min(left) >= -4000
assert max(left) >= 3900 and min(left) <= -3900
assert left[0] == left[-1] == 0
assert (OUT / 'source.py').read_bytes() == Path(__file__).with_name('y-moderate-tone.py').read_bytes()
for side in ('pre', 'post'):
    power = json.loads((OUT / f'{side}-power.json').read_text())
    assert power['ac_online'] == '1'
    assert 'ldo14                      1' in (OUT / f'{side}-regulators.txt').read_text()
    gpio = (OUT / f'{side}-gpio.txt').read_text()
    assert 'gpio-1   (                    |powerdown           ) in  lo ACTIVE LOW' in gpio
    assert 'gpio-2   (                    |powerdown           ) in  lo ACTIVE LOW' in gpio
delta = (OUT / 'kernel-delta.log').read_text()
assert 'sdw:0:0:0217:2010:00:3: SPX: device=1 hw_params active_ports=1' in delta
assert 'sdw:0:0:0217:2010:00:4: SPX: device=1 excluded from this stream' in delta
assert 'sdw:0:0:0217:2010:00:4: SPX: PA DAPM event' not in delta
assert 'sdw:0:0:0217:2010:00:4: SPX: RDAC DAPM event' not in delta
assert 'SPX ASM stream 1: bits=16 submitted=' in delta
assert 'device=1 DAC slave port 1 -> master DP1 (swap=0)' in delta
final = json.loads((Y / 'independent-result-review.json').read_text())
assert final['boot_id'] == BID and final['scoped_passed'] and final['fallback_stopped']
review = {'attempt': '20260927y', 'boot_id': BID,
          'test_manifest_sha256': sha(OUT / 'sha256.json'),
          'files_verified': len(actual), 'aplay_exit_code': 0,
          'peak_sample': max(abs(min(left)), max(left)),
          'right_channel_zero': True, 'left_only_stream_configured': True,
          'dsp_buffers_submitted': True, 'new_soundwire_errors': 0,
          'ac_online': True, 'gpio_inputs_unchanged': True,
          'physical_audio_verified': False}
(Y / 'independent-moderate-tone-review.json').write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps(review, indent=2))
