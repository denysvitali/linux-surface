#!/usr/bin/python3
"""Ensure missing/ambiguous buffer messages cannot become a persistence finding."""
import importlib.util,json
from pathlib import Path
p=Path(__file__).with_name('review-ap-persistence.py');spec=importlib.util.spec_from_file_location('persistence_review',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
base=0x9a480000;stride=(0xe0000//3)&~1
zones=[(f'ramoops:dmesg({i}/2)',base+i*stride,stride) for i in range(3)]+[('ramoops:console',base+3*stride,0x20000)]
def raw(state):
 lines=[]
 for label,addr,size in zones:
  lines += ['<7>[    0.012000] ramoops: '+state,
      f'<7>[    0.012001] ramoops: attached {label} 0x{size:x}@0x{addr:x}: 12 header, {size-12} data, 0 ecc (0/0)']
 return '\n'.join(lines)
positive=0
for state,kind in (('found existing empty buffer','empty'),('found existing buffer, size 100, start 80','valid'),('no valid data in buffer (sig = 0x00000000)','signature-mismatch'),('found existing invalid buffer, size 999999, start 1000000','invalid')):
 r=m.interpret(raw(state));assert r['diagnostic_complete'] and r['console_old_state']['kind']==kind
 assert not r['callback_execution_proven'] and not r['retention_loss_location_identified'];positive+=1
valid=raw('no valid data in buffer (sig = 0x00000000)')
bad=['', '\n'.join(valid.splitlines()[:-1]), '\n'.join(valid.splitlines()[1:]), valid+'\n'+valid,
 valid.replace('ramoops:console','ramoops:wrong'),valid.replace('0x9a55fffe','0x9a560000'),
 valid.replace('12 header','16 header'),valid.replace('sig = 0x00000000','sig = unparsed'),
 valid.replace('<7>[    0.012001] ramoops: attached ramoops:console', '<7>[    0.012000] ramoops: found existing empty buffer\n<7>[    0.012001] ramoops: attached ramoops:console')]
for sample in bad:
 r=m.interpret(sample);assert not r['diagnostic_complete'] and r['console_old_state'] is None
print(json.dumps(dict(positive_cases=positive,negative_cases=len(bad),expected_console_address=hex(base+3*stride),hardware_access=False),indent=2))
