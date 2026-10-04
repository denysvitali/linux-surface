#!/usr/bin/python3
"""Independently rehash and interpret Y's two bounded audio tests."""

import hashlib
import json
import os
from pathlib import Path

os.umask(0o077)
Y = Path('/var/lib/spx-boot-diagnostics/attempts/20260927y')
BID = 'b5f0a540-3e81-4415-b08c-f869e01349a2'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def verify(name):
    root = Y / name
    expected = json.loads((root / 'sha256.json').read_text())
    actual = {p.name: sha(p) for p in root.iterdir() if p.is_file()
              and p.name != 'sha256.json'}
    assert actual == expected
    return root, sha(root / 'sha256.json'), len(actual)


assert os.geteuid() == 0 and not (Y / 'independent-early-tests-review.json').exists()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BID
mroot, msha, mfiles = verify('mixer-read-test')
proot, psha, pfiles = verify('silent-pcm-test')
m = json.loads((mroot / 'report.json').read_text())
p = json.loads((proot / 'report.json').read_text())
assert m['boot_id'] == p['boot_id'] == BID
assert m['passed'] and m['smart_boost_control_numids'] == [94, 100]
assert all(code == 0 for code in m['command_exit_codes'].values())
assert all(count == 0 for count in m['kernel_delta_markers'].values())
assert 'SpkrLeft Smart Boost Level' in (mroot / 'cget-94.stdout').read_text()
assert 'SpkrRight Smart Boost Level' in (mroot / 'cget-100.stdout').read_text()
assert ': values=7' in (mroot / 'cget-94.stdout').read_text()
assert ': values=7' in (mroot / 'cget-100.stdout').read_text()
assert p['signal'] == 'digital zero' and p['aplay_exit_code'] == 0
assert all(p['kernel_delta_markers'][key] == 0 for key in (
    'swrm_wait_for_wr_fifo_avail err write overflow',
    'swrm_wait_for_rd_fifo_avail err read underflow',
    'Update Slave status failed', 'Slave 1 initialization failed',
    'Failed to change PA gain'))
delta = (proot / 'kernel-delta.log').read_text()
left = 'sdw:0:0:0217:2010:00:3: '
right = 'sdw:0:0:0217:2010:00:4: '
assert left + 'SPX: device=1 hw_params active_ports=1' in delta
assert right + 'SPX: device=1 excluded from this stream' in delta
assert left + 'SPX: PA DAPM event 0x1' in delta
assert right + 'SPX: PA DAPM event' not in delta
assert right + 'SPX: RDAC DAPM event' not in delta
assert right + 'SPX: device=1 hw_params active_ports=1' not in delta
assert 'SPX ASM stream 1: bits=16 submitted=11 write_done=10' in delta
assert (p['pre_soundwire'] == p['post_soundwire'] and
        sum(v['status'] == 'Attached' for v in p['post_soundwire'].values()) == 1)
report = {'attempt': '20260927y', 'boot_id': BID,
          'mixer_test_manifest_sha256': msha, 'mixer_test_files_verified': mfiles,
          'silent_test_manifest_sha256': psha, 'silent_test_files_verified': pfiles,
          'left_control_read': True, 'right_control_read_without_underflow': True,
          'attached_only_silent_stream': True, 'dsp_buffers_submitted': True,
          'physical_audio_verified': False}
(Y / 'independent-early-tests-review.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
