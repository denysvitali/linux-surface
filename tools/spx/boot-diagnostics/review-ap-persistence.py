#!/usr/bin/python3
"""Bind AP's early ramoops buffer findings to zone labels, retaining raw evidence."""
import json,re


def interpret(raw):
    state_patterns = (
        ('empty', r'found existing empty buffer'),
        ('signature-mismatch', r'no valid data in buffer \(sig = 0x([0-9a-fA-F]+)\)'),
        ('valid', r'found existing buffer, size (\d+), start (\d+)'),
        ('invalid', r'found existing invalid buffer, size (\d+), start (\d+)'),
    )
    attached = re.compile(r'attached (\S+) 0x([0-9a-fA-F]+)@0x([0-9a-fA-F]+): (\d+) header, (\d+) data, (\d+) ecc \((\d+)/(\d+)\)')
    pending=[];zones=[];issues=[];selected=[]
    for number,line in enumerate(raw.splitlines(),1):
        if 'ramoops: ' not in line:continue
        msg=line.split('ramoops: ',1)[1]
        for kind,pattern in state_patterns:
            m=re.fullmatch(pattern,msg)
            if m:
                state=dict(kind=kind,raw_line=number)
                if kind=='signature-mismatch':state['observed_signature']='0x'+m[1].lower()
                if kind in ('valid','invalid'):state.update(size=int(m[1]),start=int(m[2]))
                pending.append(state);selected.append(line);break
        else:
            m=attached.fullmatch(msg)
            if m:
                selected.append(line)
                zone=dict(label=m[1],size=int(m[2],16),address=int(m[3],16),header_bytes=int(m[4]),data_bytes=int(m[5]),ecc_bytes=int(m[6]),raw_line=number,old_states=pending)
                if len(pending)!=1:issues.append('missing or ambiguous old state for '+m[1])
                zones.append(zone);pending=[]
            elif msg.startswith(('found existing','no valid data in buffer','attached ramoops:')):
                issues.append('unparsed diagnostic at line '+str(number));selected.append(line)
    if pending:issues.append('old-buffer diagnostic without following zone')
    # Follow the archived ram.c division/alignment, not an assumed record stride.
    base=0x9a480000;total=0x100000;console=0x20000;record=0x40000
    count=(total-console)//record;stride=((total-console)//count)&~1
    expected=[(f'ramoops:dmesg({i}/{count-1})',base+i*stride,stride) for i in range(count)]
    expected.append(('ramoops:console',base+count*stride,console))
    if [(z['label'],z['address'],z['size']) for z in zones]!=expected:
        issues.append('zone order, labels, addresses or sizes differ from archived source layout')
    for z in zones:
        if z['header_bytes']!=12 or z['data_bytes']+z['header_bytes']+z['ecc_bytes']!=z['size'] or z['ecc_bytes']!=0:
            issues.append('unexpected header/data/ecc layout for '+z['label'])
    complete=not issues
    old=zones[-1]['old_states'][0] if complete else None
    return dict(diagnostic_complete=complete,zones=zones,issues=issues,console_old_state=old,
        selected_lines=selected,console_expected_address=hex(base+count*stride),
        retention_loss_location_identified=False,callback_execution_proven=False)


def main():
    import os,shutil,sys
    from pathlib import Path
    sys.path.insert(0,'/usr/local/lib/spx-boot-diagnostics')
    from ap_boot_guard import X,load,recovery,artifacts,files,sha,command
    os.umask(0o077)
    a=load();bid=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert bid!=a['preboot_id'] and os.uname().release==a['release']
    assert Path('/proc/cmdline').read_text().split()==['BOOT_IMAGE=/spx-trial-20261001am/vmlinuz']+a['cmdline'].split()
    assert a['cmdline'].split().count('ramoops.dyndbg=+p')==1
    assert not recovery(a).get('next_entry','');artifacts(a)
    root=X/'handoff-review';h=json.loads((root/'sha256.json').read_text())
    assert files(root)==h|{'sha256.json':sha(root/'sha256.json')}
    handoff=json.loads((root/'report.json').read_text());assert handoff['actual_boot_id']==bid
    raw=command('dmesg','--raw');report=interpret(raw)
    catalog=Path('/sys/kernel/debug/dynamic_debug/control').read_text()
    sites=[line for line in catalog.splitlines() if line.startswith(('fs/pstore/ram.c:','fs/pstore/ram_core.c:'))]
    report.update(attempt=a['attempt'],boot_id=bid,preboot_id=a['preboot_id'],checklist_ids=['R01','I01'],
        enabled_debug_sites=sites,all_five_sites_enabled=len(sites)==5 and all('[ramoops]' in s and re.search(r' =\S*p\S* ',s) for s in sites),
        callback_execution_proven=handoff['candidate_shutdown_software_completion_verified'],
        handoff_manifest_sha256=sha(root/'sha256.json'),
        limits=['Signature mismatch identifies lost/changed signature before probe, not which component wrote it.',
                'No old console is not proof that the outgoing callback failed to execute.',
                'A retained identity-bound completion proves software return, not electrical rail-off.'])
    out=X/'persistence-review';assert not out.exists();out.mkdir(mode=0o700)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'dmesg-raw.log').write_text(raw+'\n')
    (out/'dynamic-debug-sites.txt').write_text('\n'.join(sites)+'\n')
    (out/'cmdline').write_text(Path('/proc/cmdline').read_text())
    shutil.copy2(__file__,out/Path(__file__).name)
    h=files(out);(out/'sha256.json').write_text(json.dumps(h,indent=2)+'\n');assert files(out)==h|{'sha256.json':sha(out/'sha256.json')}
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==bid;os.sync()
    print(json.dumps(report|dict(manifest_sha256=sha(out/'sha256.json')),indent=2))

if __name__=='__main__':main()
