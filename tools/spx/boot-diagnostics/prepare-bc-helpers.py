#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create uninstalled BC helpers from the exact frozen BB runtime plan."""
import ast
import hashlib
import json
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent
PARENT = Path('/var/lib/spx-boot-diagnostics/attempts/20261004bb/build/runtime-plan')
NAMES = ('bb_boot_guard.py', 'bb-video.py', 'bb-return.py', 'bb-baseline.py',
         'bb-camera-provider.py', 'bb-camera-control.py', 'bb_camera_core.py',
         'review-bb-baseline.py', 'bb-media.py', 'bb-media-run.py',
         'bb-reboot-check.py', 'deploy-bb.py', 'review-bb-preparation.py',
         'review-bb-deployment.py', 'prepare-bb-runtime.py')


def main():
    manifest = json.loads((PARENT / 'sha256.json').read_text())
    assert hashlib.sha256((PARENT / 'sha256.json').read_bytes()).hexdigest() == \
        '9fff3050961271879ea10184fc7216af63dfedf1fcb7a31a8aa1dd4f6458e22d'
    pending = {}
    for name in NAMES:
        target = re.sub(r'\bbb(?=[-_.])', 'bc', name)
        origin = PARENT / name
        assert hashlib.sha256(origin.read_bytes()).hexdigest() == manifest[name]
        text = origin.read_text()
        text = text.replace('20261004bb', '20261004bc').replace('20261004ba', '20261004bb')
        text = re.sub(r'\bbb(?=[-_.])', 'bc', text)
        text = re.sub(r'\bBB\b', 'BC', text).replace('ba_boot_guard', 'bb_boot_guard')
        text = text.replace('a824008e-cf43-4287-84f8-4e930fa41a06',
                            'e00a2d25-03f7-4265-b56e-0eac05b234d3')
        text = text.replace('boot_dtb_exact_parent_ba', 'boot_dtb_exact_parent_bb')
        text = text.replace("review['pas_diagnostic_native_checks'] == 91", "review['pas_diagnostic_native_checks'] == 436")
        text = text.replace("review['pas_diagnostic_negative_controls'] == 5", "review['pas_diagnostic_negative_controls'] == 9")
        if name in ('prepare-bb-runtime.py', 'deploy-bb.py'):
            old = "    cmdline = parent['cmdline'].replace('spx_attempt=20261004bb', 'spx_attempt=20261004bc') + ' qcom_scm.spx_pas_diag=1'\n"
            assert text.count(old) == 1
            line = "    cmdline = parent['cmdline'].replace('spx_attempt=20261004bb', 'spx_attempt=20261004bc') + ' qcom_scm.spx_pas_area_diag=1'\n"
            expected = "    assert cmdline.split().count('qcom_scm.spx_pas_diag=1') == 1\n"
            expected += "    assert cmdline.split().count('qcom_scm.spx_pas_area_diag=1') == 1\n"
            text = text.replace(old, line + expected)
        if name == 'prepare-bb-runtime.py':
            old = "            ('duplicate-pas-diag', dict(cmdline=expected + ' qcom_scm.spx_pas_diag=1'))]:"
            assert old in text
            text = text.replace(old,
                "            ('duplicate-pas-diag', dict(cmdline=expected + ' qcom_scm.spx_pas_diag=1')),\n"
                "            ('missing-area-diag', dict(cmdline=expected.replace(' qcom_scm.spx_pas_area_diag=1', ''))),\n"
                "            ('disabled-area-diag', dict(cmdline=expected.replace('qcom_scm.spx_pas_area_diag=1', 'qcom_scm.spx_pas_area_diag=0'))),\n"
                "            ('duplicate-area-diag', dict(cmdline=expected + ' qcom_scm.spx_pas_area_diag=1'))]:")
            text = text.replace("pas_diagnostic_selector='qcom_scm.spx_pas_diag=1',",
                "pas_diagnostic_selector='qcom_scm.spx_pas_diag=1', area_query_selector='qcom_scm.spx_pas_area_diag=1',")
        if name == 'deploy-bb.py':
            old = "== {'spx_attempt=20261004bc', 'qcom_scm.spx_pas_diag=1'}"
            assert old in text
            text = text.replace(old, "== {'spx_attempt=20261004bc', 'qcom_scm.spx_pas_area_diag=1'}")
            text = text.replace("entry.replace('BA ICC and Iris1 startup', 'BC PAS diagnostic and Iris1 startup')",
                                "entry.replace('BB PAS diagnostic and Iris1 startup', 'BC PIL area query and Iris1 startup')")
            text = text.replace('pas_diagnostics_requested=True,',
                                'pas_diagnostics_requested=True, pas_area_query_requested=True,')
            # The frozen plan includes the same logger/units and strict baseline.
        if name == 'bb-video.py':
            old = "    result = dict(utc=datetime.now(timezone.utc).isoformat(), attempt=a['attempt'], boot_id=boot,"
            assert old in text
            new = "    parameters = {}\n"
            new += "    for name in ('spx_pas_diag', 'spx_pas_area_diag'):\n"
            new += "        path = Path('/sys/module/qcom_scm/parameters') / name\n"
            new += "        parameters[name] = dict(value=path.read_text().strip(), mode=oct(path.stat().st_mode & 0o777))\n"
            new += "        assert parameters[name] == dict(value='Y', mode='0o400')\n"
            new += "    (root / 'pas-parameters.json').write_text(json.dumps(parameters, indent=2) + '\\n')\n"
            text = text.replace(old, new + old)
            text = text.replace('physical_firmware_allocation_passed=False,',
                'pas_parameters=parameters, memory_area_result_uninterpreted=True, physical_firmware_allocation_passed=False,')
        if name == 'review-bb-preparation.py':
            text = text.replace("preserving BA's actual return", "preserving BB's actual return")
        ast.parse(text)
        assert not (SRC / target).exists(), target
        pending[target] = text
    assert len(pending) == 15
    for name, text in pending.items():
        with (SRC / name).open('x') as stream:
            stream.write(text)
    print('Created and parsed 15 distinct BC helpers; no installation')


if __name__ == '__main__':
    main()
