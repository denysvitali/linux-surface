#!/usr/bin/python3
"""Verify AJ collector/reviewer preserve AI criteria, with identity-only changes."""
from pathlib import Path
root=Path(__file__).resolve().parent
for old,new in [('ai-finalize.py','aj-finalize.py'),('review-ai-result.py','review-aj-result.py')]:
 expected=(root/old).read_text().replace('20260930ai','20260930aj').replace('20260930ah','20260930ai').replace('b1485998-0a40-46b7-bd77-88796fa99a89','81412181-f873-4ba8-a5fe-07f5376bf680').replace('spx-ai-','spx-aj-').replace('spx-ah-','spx-ai-').replace('ai-finalize.py','aj-finalize.py').replace('ai-reboot-check.py','aj-reboot-check.py').replace('AI','AJ').replace('ai_timers','aj_timers').replace('107-ai','108-aj')
 assert (root/new).read_text()==expected,new
print('AJ collector/reviewer identical to AI after identity substitution')
