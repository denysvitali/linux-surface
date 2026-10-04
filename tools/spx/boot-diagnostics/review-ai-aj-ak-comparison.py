#!/usr/bin/python3
"""Compare frozen pin2 trials, isolated codec deltas, and bounded command evidence."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
os.umask(0o077)
base = Path('/var/lib/spx-boot-diagnostics/attempts')
out = base / '20260930ak/ai-aj-ak-comparison.json'
assert os.geteuid() == 0 and not out.exists()
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def chunks(b):
    return {s.split(b'\n',1)[0]:s for s in re.split(b'(?=^diff --git )',b,flags=re.M) if s.startswith(b'diff --git ')}
def assignment(t,name):
    return next(n.value for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(q,ast.Name) and q.id==name for q in n.targets))
records = []
previous = None
for suffix in ('ai','aj','ak'):
    run = base / ('20260930' + suffix)
    root = run / 'final-result'
    hashes = json.loads((root / 'sha256.json').read_text())
    assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()} == hashes | {'sha256.json':sha(root / 'sha256.json')}
    a = json.loads((run / 'attempt.json').read_text())
    result = json.loads((root / 'result.json').read_text())
    review = json.loads((run / 'independent-result-review.json').read_text())
    assert review['boot_id'] == result['boot_id'] and review['result_manifest_sha256'] == sha(root / 'sha256.json')
    assert result['attempt'] == a['attempt'] == '20260930' + suffix
    selectors = [s for s in a['cmdline'].split() if not s.startswith('spx_attempt=')]
    assert 'wcd934x.spx_wsa_en_pin=2' in selectors and 'soundwire_qcom.spx_force_attach=0' in selectors
    config = set((run / 'build/artifacts/.config').read_text().splitlines())
    diff = chunks((run / 'build/source.diff').read_bytes())
    collector = ast.parse((run / 'deployment-sources' / (suffix + '-finalize.py')).read_text())
    payloads = json.loads((run / 'archive-review.json').read_text())['boot_payload_sha256']
    dtb = payloads['artifacts/arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb']
    assert dtb == '5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5'
    if previous:
        assert selectors == previous['selectors']
        assert ast.dump(assignment(collector,'passed')) == previous['scope']
        key = b'diff --git a/sound/soc/codecs/wsa881x.c b/sound/soc/codecs/wsa881x.c'
        assert {k:v for k,v in diff.items() if k != key} == {k:v for k,v in previous['diff'].items() if k != key}
        assert previous['config'] - config == {'CONFIG_LOCALVERSION="-spx-mainline-20260930' + previous['suffix'] + '"'}
        assert config - previous['config'] == {'CONFIG_LOCALVERSION="-spx-mainline-20260930' + suffix + '"'}
    previous = {'selectors':selectors,'scope':ast.dump(assignment(collector,'passed')),'config':config,'diff':diff,'suffix':suffix}
    history = result['command_history']['dumps']
    records.append({'attempt':a['attempt'],'boot_id':result['boot_id'],'release':a['release'],
                    'uptime_seconds':result['uptime_seconds'],'passed':result['passed_scoped_baseline'],
                    'scoped_failure_reasons':review['scoped_failure_reasons'],
                    'native_command_error_lines':result['native_bus_error_lines'],
                    'last_captured_submission':history[-1]['records'][-1] if history else None,
                    'touch_ready':result['spi_hid_ready'],'touch_clean_startup':result['touch_startup_clean'],
                    'result_manifest_sha256':sha(root / 'sha256.json'),
                    'full_source_diff_sha256':sha(run / 'build/source.diff'),'config_sha256':sha(run / 'build/artifacts/.config')})
old = (base / '20260930ai/post-result-records/wsa881x-before.c').read_text()
gain = (base / '20260930aj/post-result-records/wsa881x-before.c').read_text()
boost = (base / '20260930aj/boost-switch-guard-candidate/wsa881x.c').read_text()
gain_guard = '\tif (!wsa881x_spx_slave_available(wsa881x))\n\t\treturn -ENODEV;\n\n'
boost_guard = '\tif (portidx == WSA881X_PORT_BOOST &&\n\t    !wsa881x_spx_slave_available(data))\n\t\treturn -ENODEV;\n\n'
assert gain.replace(gain_guard,'',1) == old
assert boost.replace(boost_guard,'',1) == gain
assert sha(base / '20260930aj/boost-switch-guard-candidate/wsa881x.c') == json.loads((base / '20260930ak/build/build-complete.json').read_text())['source_sha256']['sound/soc/codecs/wsa881x.c']
report = {'trials':records,'selectors_identical_except_attempt_marker':True,
          'corrected_DTB_identical':True,'strict_collector_criteria_identical':True,
          'other_tracked_source_deltas_unchanged':True,'config_only_LOCALVERSION_changed':True,
          'AI_to_AJ_only_PA_gain_availability_guard':True,'AJ_to_AK_only_BOOST_switch_availability_guard':True,
          'limits':['Different boots have different timing, responding firmware state, and service activity.',
                    'An empty error-triggered history does not establish absence of all device-zero requests.',
                    'Recent software submissions do not prove causal command failure or hardware acknowledgment.',
                    'No acoustic output, PCM functionality, physical GPIO levels or reliability claim is established.']}
out.write_text(json.dumps(report,indent=2)+'\n')
os.sync()
print(json.dumps(report,indent=2))
