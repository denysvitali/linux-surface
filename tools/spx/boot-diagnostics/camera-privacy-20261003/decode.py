#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Decode retained PRLD bitfields against hash-pinned vendor instructions offline."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

OUT = Path(sys.argv[1]); assert not OUT.exists(); OUT.mkdir(mode=0o700)
ROOT = Path('/home/dvitali/Documents/drivers/FileRepository')
DSL = Path('/home/dvitali/Documents/acpi/surface_pro_x_sq2/dsdt.dsl')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(DSL) == 'e1e8da6b7464475f10e8208c108d1c15515e4357aa8b88e79bd93136ae5c50b8'
platform = ROOT/'qccamplatform8180.inf_arm64_a7101f8f98d7c572/qccamplatform8180.sys'
assert sha(platform) == '88172ff32ddd3b004dfcd0152eb32cfd17971f7860e4d8eccad0b917e016165e'
b = platform.read_bytes(); md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)

def disassemble(start,end):
    offset = 0x400+start-0x140001000
    insns = list(md.disasm(b[offset:offset+end-start],start))
    assert len(insns) == (end-start)//4
    return {i.address:(i.mnemonic,i.op_str) for i in insns}

parser=disassemble(0x1400019d8,0x140001dd0)
dispatch=disassemble(0x140001df0,0x140002118)
anchors={
  0x140001c94:('and','w8, w9, #1'),
  0x140001c98:('strb','w8, [x11], #6'),
  0x140001c9c:('lsr','w9, w9, #1'),
  0x140001ca8:('ands','w8, w9, #3'),
  0x140001cb4:('lsr','w10, w9, #2'),
  0x140001d14:('ubfx','w9, w10, #3, #1'),
  0x140001d18:('and','w8, w10, #7'),
  0x140001d4c:('add','x19, x19, #0x10'),
}
for address, expected in anchors.items(): assert parser[address] == expected,(hex(address),parser[address],expected)
assert dispatch[0x140001f98]==('cmp','w9, #0')
assert dispatch[0x140001fa0]==('csel','w24, w8, w21, ne')
assert dispatch[0x140002000]==('bl','#0x140002760')
for label, instructions in (('parser',parser),('dispatch',dispatch)):
 (OUT/(label+'.txt')).write_text('\n'.join(f'{a:#x}: {m} {s}' for a,(m,s) in instructions.items())+'\n')
source=DSL.read_text();camp=source[source.index('        Device (CAMP)'):source.index('        Device (CAMS)')]
prld=camp[camp.index('Method (PRLD'):camp.index('Method (PCFG')]
match=re.search(r'Package \(0x06\)\s*\{([^{}]*)\}',prld);assert match
values=re.findall(r'0x[0-9a-fA-F]+|Zero|One',match[1])
entries=[{'Zero':0,'One':1}[v] if v in ('Zero','One') else int(v,16) for v in values]
assert entries == [0x0101,0x0502,0,0,0,0]
resources=[int(x,16) for x in re.findall(r'Pin list\s*\n\s*(0x[0-9a-fA-F]+)',camp)]
assert resources == [11,25],resources
records=[]
for slot,entry in enumerate(entries):
 kind=(entry>>8)&3
 record={'entry':entry,'slot':slot,'sensor_mask':entry&255,'kind':kind}
 if kind==1:
  index=(entry>>10)&7;inverted=bool((entry>>13)&1)
  assert index<len(resources)
  record|={'gpio_resource_index':index,'gpio':resources[index],'inverted':inverted,
           'active_high':not inverted}
 records.append(record)
sensors=[
 ('rear','surfaceprox_camrear.inf_*','qccamrearsensor8180.sys',0xf840,0x5e34e1c5,0,'091fb0fd35c1d4d2f748983dbc460b45dd1da29dee34bc46ff85b8d2191865f9'),
 ('front','surfaceprox_camfront.inf_*','qccamfrontsensor8180.sys',0xf840,0xf27170b8,1,'4414485c49981057a2064c7ff03cc68b4d3d222af8ad9ade2a89b071adec1951'),
 ('ir','surfaceprox_camaux.inf_*','qccamauxsensor8180.sys',0xfe40,0x65528936,2,'f389ead057381503d954d5e2ca0c59294f34f8b925124f4706da3d2a2a245923')]
inputs={'firmware-dsdt.dsl':DSL,'qccamplatform8180.sys':platform,'decode.py':Path(__file__).resolve()}
identities=[]
for name,pattern,filename,offset,value,index,digest in sensors:
 matches=list(ROOT.glob(pattern));assert len(matches)==1
 p=matches[0]/filename; assert sha(p)==digest
 data=p.read_bytes(); assert struct.unpack_from('<I',data,offset)[0]==value
 assert data.count(struct.pack('<I',value))==1
 assert struct.unpack_from('<I',b,0x400+0x2118-0x1000+4*({0:0,1:2,2:1}[index]))[0]==value
 matches=[r['slot'] for r in records if r['sensor_mask']&(1<<index)]
 identities.append({'sensor':name,'guid_first_dword':value,'sensor_binary_offset':offset,
                    'dispatch_sensor_index':index,'indicator_slots':matches})
 inputs[filename]=p
(OUT/'camp-methods.txt').write_text(camp)
for name,path in inputs.items(): shutil.copyfile(path,OUT/name)
(OUT/'inputs.json').write_text(json.dumps({n:{'source':str(p),'sha256':sha(p)} for n,p in inputs.items()},indent=2)+'\n')
report={'firmware_prld_entries':entries,'decoded_indicator_records':records,'sensor_identities':identities,
 'gpio_mapping_from_firmware_resource_order':True,'active_high_decoded_from_vendor_bitfield':True,
 'physical_indicator_acceptance':False,'hardware_actions':0,
 'limits':['Static pinned vendor parser/dispatch and resource correspondence are software evidence; physical LEDs still need testing.',
           'IR selects no entry in this PRLD table; this does not establish IR illumination absence or safety/control.',
           'Unmatched six-slot records are inactive; no inference from unsupported zero entries.',
           'No camera capture, Linux GPIO request/write or vendor binary execution occurred.']}
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
h={p.name:sha(p) for p in OUT.iterdir() if p.is_file()};(OUT/'sha256.json').write_text(json.dumps(h,indent=2)+'\n')
assert all(sha(OUT/n)==v for n,v in h.items())
print(json.dumps(report|{'files_verified':len(h),'manifest_sha256':sha(OUT/'sha256.json')},indent=2))
