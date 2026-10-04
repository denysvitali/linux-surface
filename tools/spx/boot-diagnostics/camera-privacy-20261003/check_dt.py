#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile an offline AS-relative rear privacy candidate and check exact scope."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import libfdt

REPO=Path('/home/dvitali/Documents/git/linux-surface-next')
HERE=Path(__file__).resolve().parent
AS=Path('/var/lib/spx-boot-diagnostics/attempts/20261003as')
SOURCE=Path('/var/tmp/spx-mainline-trial-20261003ar/source')
BIN=Path('/var/tmp/spx-dtschema-venv-20260915/bin')
OUT=Path(sys.argv[1]);assert not OUT.exists();os.umask(0o077);OUT.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sys.path.insert(0,str(HERE.parent));from review_aq_dtb_delta_ar import flatten
base=AS/'dtb-build/spx.dtb'
assert sha(base)=='fa3b89f98697573d61bf23180bd81307de7e762e3a305b3240d087b4f4dc1561'
inputs={p:sha(p) for p in (base,AS/'dtb-build/enabled-review/candidate.pre.dts',REPO/'.config',
 REPO/'drivers/media/v4l2-core/v4l2-subdev.c',REPO/'drivers/media/v4l2-core/v4l2-fwnode.c',
 REPO/'drivers/leds/led-class.c',REPO/'drivers/leds/leds-gpio.c',HERE/'spx-rear-privacy.dtsi')}
for n in ('CONFIG_LEDS_GPIO=y','CONFIG_LEDS_CLASS=y'):
 assert n+'\n' in (AS/'build/artifacts/.config').read_text()
shutil.copyfile(AS/'dtb-build/enabled-review/candidate.pre.dts',OUT/'as-base.pre.dts')
shutil.copyfile(HERE/'spx-rear-privacy.dtsi',OUT/'spx-rear-privacy.dtsi')
(OUT/'candidate.dts').write_text('#include "as-base.pre.dts"\n#include "spx-rear-privacy.dtsi"\n')
commands=[]
def run(args,log):
 with (OUT/log).open('x') as f:
  r=subprocess.run([str(a) for a in args],stdout=f,stderr=subprocess.STDOUT,timeout=60)
 commands.append({'command':[str(a) for a in args],'log':log,'exit_code':r.returncode})
 (OUT/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');assert r.returncode==0,log
run(['gcc','-E','-nostdinc','-undef','-D__DTS__','-x','assembler-with-cpp','-I',SOURCE/'include',
 '-I',OUT,OUT/'candidate.dts','-o',OUT/'candidate.pre.dts'],'cpp.log')
run(['dtc','-I','dts','-O','dtb','-H','epapr','-o',OUT/'candidate.dtb',OUT/'candidate.pre.dts'],'dtc.log')
old=flatten(base.read_bytes());new=flatten((OUT/'candidate.dtb').read_bytes())
rear='/soc@0/cci@ac4a000/i2c-bus@0/camera@10'
root='/camera-privacy-leds';led=root+'/led-0'
assert set(new)-set(old)=={root,led} and not set(old)-set(new)
for path in old:
 right=dict(new[path])
 if path==rear:
  assert set(right)-set(old[path])=={'leds','led-names'}
  del right['leds'];del right['led-names']
 assert right==old[path],path
fdt=libfdt.Fdt((OUT/'candidate.dtb').read_bytes())
oldf=libfdt.Fdt(base.read_bytes())
assert oldf.num_mem_rsv()==fdt.num_mem_rsv()
assert all(oldf.get_mem_rsv(i)==fdt.get_mem_rsv(i) for i in range(fdt.num_mem_rsv()))
def exact(candidate):
 h=candidate.getprop(candidate.path_offset(rear),'leds').as_uint32()
 assert candidate.get_path(candidate.node_offset_by_phandle(h))==led
 assert candidate.getprop(candidate.path_offset(rear),'led-names')==b'privacy\0'
 assert candidate.getprop(candidate.path_offset(led),'default-state')==b'off\0'
 gpio=candidate.getprop(candidate.path_offset(led),'gpios')
 assert len(gpio)==12 and int.from_bytes(gpio[4:8],'big')==11 and int.from_bytes(gpio[8:12],'big')==0
 assert candidate.get_path(candidate.node_offset_by_phandle(int.from_bytes(gpio[:4],'big')))=='/soc@0/pinctrl@3100000'
 assert candidate.getprop(candidate.path_offset(root),'compatible')==b'gpio-leds\0'
exact(fdt)
schemas=OUT/'schema';shutil.copytree(AS/'dtb-build/v7/schema',schemas)
for rel in ('leds/leds-gpio.yaml','leds/common.yaml','leds/leds-consumer.yaml'):
 shutil.copyfile(SOURCE/'Documentation/devicetree/bindings'/rel,schemas/rel)
for selection in ('leds-gpio','ovti,ov13858','qcom,i2c-cci','qcom,spmi-regulator'):
 log=selection.replace(',','-')+'.log'
 run([BIN/'dt-validate','-s',schemas,'-l',selection,OUT/'candidate.dtb'],log)
 assert not (OUT/log).read_text().strip(),log
for name,prop,raw in [('wrong-gpio','gpios',None),('wrong-polarity','gpios',None),('wrong-name','led-names',b'activity\0')]:
 bad=libfdt.Fdt(fdt.as_bytearray());bad.resize(len(fdt.as_bytearray())+512)
 if raw is None:
  v=bytearray(bad.getprop(bad.path_offset(led),'gpios'))
  v[4:8]=(25 if name=='wrong-gpio' else 11).to_bytes(4,'big')
  v[8:12]=(1 if name=='wrong-polarity' else 0).to_bytes(4,'big');bad.setprop(bad.path_offset(led),prop,bytes(v))
 else: bad.setprop(bad.path_offset(rear),prop,raw)
 try:exact(bad)
 except AssertionError:pass
 else:raise AssertionError('negative fixture accepted: '+name)
 (OUT/(name+'.dtb')).write_bytes(bad.as_bytearray())
for name,path,prop,selection in [('missing-led-gpio',led,'gpios','leds-gpio'),('invalid-privacy-name',rear,'led-names','ovti,ov13858')]:
 bad=libfdt.Fdt(fdt.as_bytearray());bad.resize(len(fdt.as_bytearray())+512)
 if name.startswith('missing'):bad.delprop(bad.path_offset(path),prop)
 else:bad.setprop(bad.path_offset(path),prop,b'activity\0')
 p=OUT/(name+'.dtb');p.write_bytes(bad.as_bytearray())
 run([BIN/'dt-validate','-s',schemas,'-l',selection,p],name+'.log')
 assert prop in (OUT/(name+'.log')).read_text()
assert all(sha(p)==v for p,v in inputs.items())
(OUT/'inputs.json').write_text(json.dumps({str(p):v for p,v in inputs.items()},indent=2)+'\n')
shutil.copyfile(__file__,OUT/Path(__file__).name)
result={'base_dtb_sha256':sha(base),'candidate_dtb_sha256':sha(OUT/'candidate.dtb'),
 'new_nodes':[root,led],'only_existing_properties_added':[rear+'/leds',rear+'/led-names'],
 'all_other_nodes_properties_reservations_exact':True,'rear_gpio11_active_high_default_off':True,
 'existing_v4l2_led_lookup_and_stream_ownership':True,'positive_schema_selections':4,
 'negative_gpio_polarity_name_relations_rejected':3,'negative_schema_cases_rejected':2,
 'active_kernel_config_sources_unchanged':True,'no_new_front_ir_camss':True,'installed':False,'hardware_actions':0,
 'limits':['Physical LED, stream indicator timing and stream-failure handling need actual functional checks.',
          'No CSI receiver/capture added; analog supply/SID contract remains open.',
          'Focused schemas; existing base-board diagnostics are not full schema acceptance.']}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
h={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()}
(OUT/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert all(sha(OUT/n)==v for n,v in h.items())
print(json.dumps(result|{'files_verified':len(h),'manifest_sha256':sha(OUT/'sha256.json')},indent=2))
