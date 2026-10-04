#!/usr/bin/python3
"""Verify AK collector/reviewer retain AJ criteria after identity substitution."""
from pathlib import Path
root=Path(__file__).resolve().parent
for old,new in [('aj-finalize.py','ak-finalize.py'),('review-aj-result.py','review-ak-result.py')]:
 expected=(root/old).read_text().replace('20260930aj','20260930ak').replace('spx-aj-','spx-ak-').replace('AJ','AK')
 assert (root/new).read_text()==expected,new
print('AK collector/reviewer identical to AJ after identity substitution')
