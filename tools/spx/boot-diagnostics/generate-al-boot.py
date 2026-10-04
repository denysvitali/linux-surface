#!/usr/bin/python3
"""Reproduce AL's identity/pin-specific changes from frozen AK collectors."""
from pathlib import Path
root=Path(__file__).resolve().parent

def converted(s):
    s=s.replace('20260930ak','20260930al').replace('spx-ak-','spx-al-').replace('AK','AL')
    s=s.replace('7.3.0-rc2-spx-mainline-20260930al+','7.3.0-rc2-spx-mainline-20260930ak+').replace('/spx-trial-20260930al/','/spx-trial-20260930ak/')
    for a,b in [
        ('right_init','left_init'),('right_wsa_cold_init_markers','left_wsa_cold_init_markers'),
        ('pin2_','pin1_'),('right firmware identity matching','left firmware identity matching'),
        ('right command-history diagnostic','left command-history control'),
        ('wcd934x.spx_wsa_en_pin=2','wcd934x.spx_wsa_en_pin=1'),
        ("spx_wsa_en_pin') == '2'","spx_wsa_en_pin') == '1'"),
        ("'spx_wsa_en_pin': '2'","'spx_wsa_en_pin': '1'"),
        ('direction == 0x04 and value == 0x1c','direction == 0x02 and value == 0x1a'),
        ("{'0042': 4, '0043': 28}","{'0042': 2, '0043': 26}"),
        ('SPX: forced wcd-gpio pin 2 output-high','SPX: forced wcd-gpio pin 1 output-high'),
        ('slot=1 decoded=0217:2110 unique=4','slot=1 decoded=0217:2110 unique=3'),
        ("right = sdw_slaves.get('sdw:0:0:0217:2110:00:4'","left = sdw_slaves.get('sdw:0:0:0217:2110:00:3'"),
        ("right = sdw.get('sdw:0:0:0217:2110:00:4'","left = sdw.get('sdw:0:0:0217:2110:00:3'"),
        ('right.get(', 'left.get('),('/speaker@0,4','/speaker@0,3'),
        ('sdw:0:0:0217:2110:00:4: SPX: initializing amplifier','sdw:0:0:0217:2110:00:3: SPX: initializing amplifier')]:
        s=s.replace(a,b)
    return s

if __name__ == '__main__':
    for old,new in [('ak-finalize.py','al-finalize.py'),('review-ak-result.py','review-al-result.py')]:
        assert (root/new).read_text()==converted((root/old).read_text()),new
    print('AL collectors reproduced from AK with identity, pin1 and left-specific checks only')
