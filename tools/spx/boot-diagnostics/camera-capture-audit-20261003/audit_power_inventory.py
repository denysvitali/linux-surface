#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded retained PEP/PMIC inventory and related-SoC reference, no hardware I/O."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.request

OUT=Path(sys.argv[1]);assert not OUT.exists();OUT.mkdir(mode=0o700)
ROOT=Path('/home/dvitali/Documents/drivers/FileRepository')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
records={}
for pattern,digest in [
 ('surfaceprox_pep.inf_*/qcpep8180.sys','751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde'),
 ('qcpmic8180.inf_*/qcpmic8180.sys','56562274b7d1128ab7b54e400eee1cf75a1c04ff59a0e420e349be9902836dc2'),
 ('qcpmicapps8180.inf_*/qcpmicapps8180.sys','a7292e00d475178c4b373f971d74b4c21630e3cd806492da20ff0582638c59f2')]:
 paths=list(ROOT.glob(pattern));assert len(paths)==1;p=paths[0];assert sha(p)==digest
 b=p.read_bytes();shutil.copyfile(p,OUT/p.name)
 strings=[{'offset':m.start(),'text':m.group().decode()} for m in re.finditer(rb'[\x20-\x7e]{5,}',b)
          if re.search(rb'(?i)csi|mipi|mmcx|vdda|/arc/client/rail|/pmic/client/',m.group())]
 records[p.name]={'source':str(p),'sha256':digest,'filtered_ascii_strings':strings}
assert any(s['text']=='/arc/client/rail_mmcx' for s in records['qcpep8180.sys']['filtered_ascii_strings'])
assert sum(s['text'].startswith('cam_cc_csiphy') for s in records['qcpep8180.sys']['filtered_ascii_strings'])==4
DSL=Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')
assert sha(DSL)=='e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'camera-power-20261003'))
from audit_firmware import extract
extracted=extract(DSL.read_text());assert extracted['literal_packages_verified']==986
camera={n:s for n,s in extracted['devices'].items() if n.endswith(('CAMP','CAMS','CAMF','CAMI'))}
assert len(camera)==4
source_url='https://android.googlesource.com/kernel/msm/+/28cc5c521b21f92fa6f8a5a6be16960100f70a7a/arch/arm64/boot/dts/qcom/sm8150-camera.dtsi'
payload=urllib.request.urlopen(source_url+'?format=TEXT',timeout=30).read()
reference=base64.b64decode(payload,validate=True)
(OUT/'sm8150-camera.dtsi').write_bytes(reference)
text=reference.decode()
assert text.count('mipi-csi-vdd-supply = <&pm8150l_l3>;')==4
assert text.count('csi-vdd-voltage = <1200000>;')==4
shutil.copyfile(DSL,OUT/'firmware-dsdt.dsl')
shutil.copyfile(Path(__file__),OUT/'audit_power_inventory.py')
shutil.copyfile(Path(__file__).resolve().parent.parent/'camera-power-20261003/audit_firmware.py',OUT/'audit_firmware.py')
(OUT/'inventory.json').write_text(json.dumps(records,indent=2)+'\n')
(OUT/'camera-cpxc.json').write_text(json.dumps(camera,indent=2)+'\n')
report={'actual_soc':'SC8180X/SQ2','retained_pep_pmic_binaries_verified':3,'literal_packages_verified':986,
 'camera_devices':list(camera),'related_reference':{'soc':'SM8150','url':source_url,'sha256':sha(OUT/'sm8150-camera.dtsi'),
 'phy_nodes':4,'named_supply':'pm8150l_l3','declared_microvolts':1200000},
 'sc8180x_analog_supply_mapping_established':False,'hardware_actions':0,
 'limits':['Filtered ASCII strings are inventory, not complete call-graph or absence evidence.',
          'Related SM8150 PMIC topology and PHY generation are not SC8180X board wiring proof.',
          'Retained camera CPXC votes establish MMCX and sensor rails, not dedicated receiver analog providers.',
          'No SC8180X receiver resource or required-supply removal is justified by these inputs.']}
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
h={p.name:sha(p) for p in OUT.iterdir() if p.is_file()};(OUT/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
assert all(sha(OUT/n)==v for n,v in h.items());print(json.dumps(report|{'files_verified':len(h),'manifest_sha256':sha(OUT/'sha256.json')},indent=2))
