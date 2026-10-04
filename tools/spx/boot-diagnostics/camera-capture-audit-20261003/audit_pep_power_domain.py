#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check retained SQ2 PEP camera footswitch, GDSC and rail-client byte contracts."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path):
    sys.dont_write_bytecode = True
    spec=importlib.util.spec_from_file_location('pep_domain_image',path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def metadata(image):
    q=lambda at:struct.unpack('<Q',image.read(at,8))[0]
    d=lambda at:struct.unpack('<I',image.read(at,4))[0]
    s=lambda at:image.read(at,128).split(b'\0')[0].decode('ascii')
    base=image.base
    assert q(0x16dec8)-base == 0x136f0
    assert q(0x16deb8)-base == 0x1ee870
    assert s(0x1542e0)=='FootswitchData'
    node=0x1c07b0
    assert s(q(node)-base)=='/fs/*' and q(node+8)-base==0x89d20
    assert d(node+0x30)==2 and q(node+0x38)-base==0x187510
    resources=[]
    for at in (0x187510,0x187558):
        resources.append(dict(rva=at,name=s(q(at)-base),units=s(q(at+8)-base),maximum=d(at+0x10)))
    assert [(r['name'],r['maximum']) for r in resources]==[('/fs/*/enable',2),('/fs/*/hwctrlenable',4)]
    conversion=[]
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
    for index,offset in enumerate(struct.unpack('<4b',image.read(0x2070f4,4))):
        at=0x2070f4+offset*4
        ins=list(md.disasm(image.read(at,12),base+at))
        assert [(i.mnemonic,i.op_str) for i in ins]==[
            ('mov',f'w8, #{index+1}'),('str','w8, [sp, #0x18]'),('b',f'#{base+0x2070e8:#x}')]
        conversion.append(dict(raw=index+1,internal=index+1,target_rva=at))
    targets=[0x89f10+offset*4 for offset in struct.unpack('<4i',image.read(0x8a4f4,16))]
    assert targets==[0x89f68,0x8a018,0x89f10,0x89fc0]
    bsp=0x189850
    assert (q(bsp+0x60)-base,d(bsp+0x68))==(0x19c550,39)
    names=[];selected=[]
    expected={'bps_gdsc':0xad07004,'ife_0_gdsc':0xad0a004,'ife_1_gdsc':0xad0b004,
              'ife_2_gdsc':0xad0f004,'ife_3_gdsc':0xad0f070,'ipe_0_gdsc':0xad08004,
              'ipe_1_gdsc':0xad09004,'titan_top_gdsc':0xad0c1bc}
    for index in range(39):
        at=0x19c550+index*0x48
        name=s(q(at)-base);names.append(name)
        if name in expected:
            assert q(at+0x10)==expected[name],(name,'gdscr')
            assert q(at+0x18)-base==0x19f928,(name,'HAL')
            assert q(at+0x38)-base==0x196230,(name,'rail')
            selected.append(dict(index=index,name=name,node_rva=at,address=q(at+0x10),
                                 hal_rva=0x19f928,rail_rva=0x196230,initial_count=d(at+0x30)))
    assert len(set(names))==39 and len(selected)==8
    hal=[v-base for v in struct.unpack('<6Q',image.read(0x19f928,48))]
    assert hal==[0xff420,0xff460,0xff490,0xff4c0,0xff4f0,0xff520]
    assert (q(bsp+0x10)-base,d(bsp+0x18))==(0x189628,3)
    rails=[]
    for v in struct.unpack('<3Q',image.read(0x189628,24)):
        at=v-base;rails.append(dict(rva=at,name=s(q(at)-base),initial_missing_client_limit=d(at+0xdc)))
    assert [r['name'] for r in rails]==['/arc/client/rail_cx','/arc/client/rail_mmcx','/arc/client/rail_mx']
    properties={}
    for index in range(32):
        key,value=struct.unpack('<QQ',image.read(0x173c80+index*16,16))
        if key==0:break
        name=s(key-base);assert name not in properties
        properties[name]=value-base
    assert properties['ClockRailConfig']==0x19f240
    limits=[]
    for index in range(4):
        at=0x19f240+index*16;p=q(at)
        if p==0:break
        limits.append(dict(name=s(p-base),value=d(at+8)))
    assert limits==[dict(name='/arc/client/rail_cx',value=0),
                    dict(name='/arc/client/rail_mmcx',value=16),dict(name='/arc/client/rail_mx',value=0)]
    lists={}
    for name,at,count in [('ClockAlwaysOnList',0x19f130,33),('RefCountSuspendedList',0x18a268,2),
                          ('ExcludedPowerDomains',0x19f700,9),('SuppressibleList',0x19f560,38),
                          ('ForceMemCoreAndPeriphList',0x19f280,91)]:
        assert properties[name]==at
        rows=[]
        for index in range(count+1):
            pointer=q(at+index*8)
            if pointer==0:break
            rows.append(s(pointer-base))
        assert index==count and len(rows)==len(set(rows))==count,(name,'list length')
        lists[name]=dict(rva=at,names=rows)
    assert all(not n.startswith('cam_cc_') for name in ('ClockAlwaysOnList','RefCountSuspendedList','SuppressibleList') for n in lists[name]['names']), 'camera default-list membership'
    assert not set(expected)&set(lists['ExcludedPowerDomains']['names']), 'camera domain exclusion'
    assert len([n for n in lists['ForceMemCoreAndPeriphList']['names'] if n.startswith('cam_cc_')])==20
    return dict(resource_templates=resources,parser_vtable_name_slot=0x16dec8,
                action_conversion=conversion,dispatch_targets=targets,bsp_rva=bsp,
                domain_count=39,domain_stride=72,camera_domains=selected,hal_functions=hal,
                rail_descriptors=rails,clock_rail_config=limits,default_lists=lists,
                dedicated_analog_supplier_established=False,live_bsp_observed=False)


CONTRACTS={
    0x136f8:'adrp x8, #0x140154000',0x136fc:'add x0, x8, #0x2e0',0x13704:'ret',
    0x1ee914:'bl #0x140206f18',0x1ee920:'add x9, x8, #0x20',0x1ee928:'str w8, [x9]',
    0x1eb36c:'cmp w8, #0xf',0x1eb38c:'ldr w3, [x9]',0x1eb39c:'bl #0x1401f2d80',
    0x1f337c:'ldr w8, [sp, #0x58]',0x1f3380:'str w8, [x9]',0x1f33a0:'bl #0x14008a518',
    0x8aae8:'bl #0x1400f2db0',0x8bb7c:'add x10, x8, #0x510',
    0x8beb4:'add x10, x8, #0x7b0',0x8bf18:'bl #0x140105848',
    0x8bf24:'ldr w8, [x8]',0x8bf28:'cmp w8, #1',0x8bf3c:'cmp w8, #2',
    0xf2de0:'ldr w20, [x8, #0x68]',0xf2de8:'ldr x23, [x8, #0x60]',0xf2dec:'mov x24, #0x48',
    0xf2e00:'bl #0x140153eac',0xf2e24:'orr x9, x8, #0x20000',
    0x89ef0:'cmp w8, #3',0x89efc:'adr x9, #0x14008a4f4',0x89f04:'adr x9, #0x140089f10',
    0x89fb0:'bl #0x1400f2e60',0x8a188:'bl #0x1400f2fa8',
    0x89f58:'bl #0x1400f3008',0x89fc8:'bl #0x1400f3278',
    0xf2e68:'ubfx x9, x0, #0x10, #0x10',0xf2e6c:'cmp w9, #2',
    0xf2e94:'madd x1, x11, x12, x8',0xf2ea0:'bl #0x1400f8358',0xf2fe4:'bl #0x1400f8578',
    0xf83b8:'ldr w8, [x19, #0x30]',0xf83bc:'cbnz w8, #0x1400f8504',
    0xf83c0:'ldr x20, [x19, #0x38]',0xf83cc:'add x22, x19, #0x40',
    0xf83d0:'ubfx w23, w8, #9, #1',0xf8430:'sub w8, w8, #1',
    0xf8438:'mov w1, #0x30',0xf846c:'bl #0x1400fc5b0',0xf8480:'bl #0x1400fc5b0',
    0xf8484:'add x20, x19, #0x10',0xf848c:'ldr x8, [x20, #8]',0xf8494:'ldr x22, [x8]',
    0xf84b0:'blr x22',0xf8508:'add w9, w8, #1',0xf850c:'str w9, [x19, #0x30]',
    0xf8608:'ldr x22, [x8, #8]',0xf8624:'blr x22',0xf8628:'ldr x8, [x19, #0x38]',
    0xf8644:'bl #0x1400fe0a0',0xf8694:'bl #0x1400fc7b0',
    0xfc5c4:'ldr w12, [x20, #0x58]',0xfc610:'ldr x10, [x20, #0x60]',
    0xfc618:'ldr w8, [x1, #0xdc]',0xfc620:'b.gt #0x1400fc6d4',
    0xfc650:'ldr x0, [x20, #0x60]',0xfc654:'mov w1, w19',0xfc658:'bl #0x140102cc8',
    0xfc6bc:'str w19, [x20, #0x58]',0xfc824:'bl #0x1400fc728',0xfc830:'sub w8, w8, #1',
    0xfc874:'bl #0x1400fc5b0',0xfc888:'bl #0x1400fc5b0',
    0xf55b4:'bl #0x1400fcae8',0xfcb10:'ldr w8, [x9, #0x18]',0xfcb28:'ldr x8, [x9, #0x10]',
    0xfcb38:'add x23, x24, #0xdc',0xfcb54:'add x1, x10, #0x1f0',
    0xfcb5c:'bl #0x140153eac',0xfcba4:'bl #0x140153eac',0xfcbcc:'str w9, [x23]',
    0xfcc48:'add x3, x8, #0x8c0',0xfcc54:'bl #0x1401081d8',
    0xfc92c:'ldr x0, [x19]',0xfc938:'mov w2, #0x40',0xfc940:'bl #0x1401029e8',
    0xfc944:'str x0, [x19, #0x68]',0xfc95c:'mov w2, #0x800',0xfc964:'bl #0x1401029e8',
    0xfc968:'str x0, [x19, #0xd0]',0xfc97c:'ldr w1, [x19, #0x60]',0xfc980:'cbz w1, #0x1400fca08',
    0xfc98c:'bl #0x140102cc8',0xfca10:'ldr w1, [x19, #0xc8]',0xfca20:'bl #0x140102cc8',
    0xff428:'ldr x9, [x0]',0xff434:'bl #0x1400fdfc8',0xff438:'and w1, w0, #0xfffffffe',
    0xff440:'bl #0x1400fe1e8',0xff448:'bl #0x1400fdfc8',0xff44c:'tbz w0, #0x1f, #0x1400ff444',
    0xff478:'orr w1, w0, #1',0xff480:'bl #0x1400fe1e8',0xff4a4:'tbnz w0, #0, #0x1400ff4b4',
    0xff4d4:'tbz w0, #0x1f, #0x1400ff4e4',0xff508:'orr w1, w0, #2',
    0xff538:'and w1, w0, #0xfffffffd',0xfdfcc:'ldr w8, [x0]',
    0xfe1e8:'str w1, [x0]',0xfe1ec:'ret',
}


def instructions(image):
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
    rows=[]
    for at,expected in CONTRACTS.items():
        decoded=list(md.disasm(image.read(at,4),image.base+at))
        assert len(decoded)==1,hex(at)
        ins=decoded[0];actual=(ins.mnemonic+' '+ins.op_str).strip()
        assert actual==expected,(hex(at),actual,expected)
        rows.append(dict(rva=at,instruction=actual,bytes=image.read(at,4).hex()))
    return rows


def linux(camcc,gdsc,header):
    domains=[]
    for name in ('bps_gdsc','ife_0_gdsc','ife_1_gdsc','ife_2_gdsc','ife_3_gdsc','ipe_0_gdsc','ipe_1_gdsc','titan_top_gdsc'):
        body=re.search(r'static struct gdsc '+name+r' = \{(.*?)\n\};',camcc,re.S).group(1)
        offset=int(re.search(r'\.gdscr = (0x[0-9a-f]+)',body).group(1),16)
        assert '.flags = POLL_CFG_GDSCR' in body
        parent='titan_top_gdsc' if name!='titan_top_gdsc' else None
        if parent:
            assert '.parent = &titan_top_gdsc.pd' in body
        else:
            assert '.parent =' not in body
        domains.append(dict(name=name,address=0xad00000+offset,poll_cfg=True,parent=parent))
    for name,bit in [('PWR_ON_MASK',31),('SW_COLLAPSE_MASK',0),('HW_CONTROL_MASK',1),
                     ('GDSC_POWER_UP_COMPLETE',16),('GDSC_POWER_DOWN_COMPLETE',15)]:
        assert re.search(r'#define '+name+r'\s+BIT\('+str(bit)+r'\)',gdsc),name
    assert re.search(r'#define POLL_CFG_GDSCR\s+BIT\(5\)',header)
    return dict(domains=domains,shared_masks=dict(power_on=0x80000000,collapse=1,hwcontrol=2),
                different_status_registers=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[4])
    args=parser.parse_args();out=args.output;out.mkdir(mode=0o700)
    prior=Path('/var/tmp/spx-pep-clock-contract-20261003-v2')
    receiver=Path('/var/tmp/spx-receiver-power-20261003-v1')
    paths={name:prior/name for name in ('qcpep8180.sys','dsdt.dsl','audit_pep_loader.py')}
    paths.update({'prior-clock.json':prior/'pep-clock.json','prior-clock-SHA256SUMS':prior/'SHA256SUMS',
                  'receiver-power.json':receiver/'receiver-power.json','receiver-SHA256SUMS':receiver/'SHA256SUMS',
                  'gdsc.c':args.repo/'drivers/clk/qcom/gdsc.c','gdsc.h':args.repo/'drivers/clk/qcom/gdsc.h',
                  'camcc-sc8180x.c':args.repo/'drivers/clk/qcom/camcc-sc8180x.c',
                  'sc8180x.dtsi':args.repo/'arch/arm64/boot/dts/qcom/sc8180x.dtsi',
                  'audit_pep_power_domain.py':Path(__file__)})
    inputs={}
    for name,path in paths.items():
        shutil.copyfile(path,out/name);assert sha(path)==sha(out/name)
        inputs[name]=dict(path=str(path),sha256=sha(path))
    assert inputs['qcpep8180.sys']['sha256']=='751c843d0a953baa94a911a7dc70cc48573605572d2a8bcd07998c739d159dde'
    assert sha(out/'prior-clock-SHA256SUMS')=='b850c47fb7fd5466f80ab5e9b10c8546f347ba9e56b39f7919fd26af39fdfe20'
    assert sha(out/'receiver-SHA256SUMS')=='7ca2b4bc51b8f01b2715a0732c139e109b5999a81cc5eff735a56e4b36518943'
    for prefix,names in [('prior-clock',['qcpep8180.sys','dsdt.dsl','audit_pep_loader.py','pep-clock.json']),('receiver',['receiver-power.json'])]:
        records=dict(line.split('  ',1)[::-1] for line in (out/(prefix+'-SHA256SUMS')).read_text().splitlines())
        for name in names:
            assert sha(out/('prior-clock.json' if name=='pep-clock.json' else name))==records[name]
    helper=module(out/'audit_pep_loader.py');image=helper.Image((out/'qcpep8180.sys').read_bytes())
    data=metadata(image);checks=instructions(image)
    current=linux((out/'camcc-sc8180x.c').read_text(),(out/'gdsc.c').read_text(),(out/'gdsc.h').read_text())
    assert {r['name']:r['address'] for r in data['camera_domains']}=={r['name']:r['address'] for r in current['domains']}
    requests=[]
    raw=json.loads((out/'receiver-power.json').read_text())
    for package,report in raw['packages'].items():
        for device,states in report['devices'].items():
            for state in states:
                for action in state['actions']:
                    if action['operation']=='FOOTSWITCH' and action['arguments'][0] in {r['name'] for r in data['camera_domains']}:
                        name,code=action['arguments'];assert code in (1,2)
                        requests.append(dict(package=package,device=device,component=state['component'],
                                             state=state['state'],line=action['line'],name=name,raw_action=code,
                                             internal_action=code,control='software'))
    assert requests and {r['name'] for r in requests}=={r['name'] for r in data['camera_domains']}
    ranges=[];listing=[]
    starts=sorted({s for at in CONTRACTS if at!=0xfe1e8 and at!=0xfe1ec for s,e in image.functions.items() if s<=at<e})
    assert all(sum(s<=at<e for s,e in image.functions.items())==1 for at in CONTRACTS if at not in (0xfe1e8,0xfe1ec))
    md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);md.skipdata=True
    for start in starts:
        end=image.functions[start];raw_range=image.read(start,end-start)
        ranges.append(dict(start_rva=start,end_rva=end,sha256=hashlib.sha256(raw_range).hexdigest(),exception_bounded=True))
        listing.append(f'Function {start:#x}..{end:#x}\n')
        listing.extend(f'{i.address-image.base:#x}: {i.mnemonic} {i.op_str}\n' for i in md.disasm(raw_range,image.base+start))
    ranges.append(dict(start_rva=0xfe1e8,end_rva=0xfe1f0,sha256=hashlib.sha256(image.read(0xfe1e8,8)).hexdigest(),
                       exception_bounded=False,boundary='Selected STR followed immediately by terminal RET; no pdata entry.'))
    listing.append('Selected unrecorded MMIO writer: STR; RET, two instructions only.\n')
    result=dict(inputs=inputs,metadata=data,linux=current,requests=requests,instruction_checks=checks,
                ranges=ranges,exception_records=len(image.functions),hardware_operations=0,
                limits=['Selected contracts and call sites do not establish full vendor CFG or actual Windows execution.',
                        'No live BSP/resource ownership or dedicated PHY/PLL analog supplier is established.',
                        'Linux CFG_GDSCR polling differs from the retained PEP PWR_ON polling; no equivalence is asserted.',
                        'Default-list absence is limited to the retained tables, not physical always-on supply proof.'])
    (out/'pep-power-domain.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'pep-power-domain-code.txt').write_text(''.join(listing))
    (out/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    print(json.dumps(dict(instruction_checks=len(checks),ranges=len(ranges),camera_domains=8,
                         firmware_actions=len(requests),manifest_sha256=sha(out/'SHA256SUMS'))))


if __name__=='__main__':
    main()
