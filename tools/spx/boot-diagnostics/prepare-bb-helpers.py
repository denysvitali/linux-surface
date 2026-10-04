#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create distinct BB helpers from BA without changing BA evidence or installation."""
import ast
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent
NAMES = ('ba_boot_guard.py', 'ba-video.py', 'ba-return.py', 'ba-baseline.py',
         'ba-camera-provider.py', 'ba-camera-control.py', 'ba_camera_core.py',
         'review-ba-baseline.py', 'ba-media.py', 'ba-media-run.py',
         'ba-reboot-check.py', 'deploy-ba.py', 'review-ba-preparation.py',
         'review-ba-deployment.py', 'prepare-ba-runtime.py')


def main():
    pending = {}
    for name in NAMES:
        target = re.sub(r'\bba(?=[-_.])', 'bb', name)
        text = (SRC / name).read_text()
        text = text.replace('20261004ba', '20261004bb').replace('20261003az', '20261004ba')
        text = re.sub(r'\bba(?=[-_.])', 'bb', text)
        text = re.sub(r'\bBA\b', 'BB', text).replace('az_boot_guard', 'ba_boot_guard')
        for old in ('19cfd105-9780-4c85-995f-625bb1eb0529',
                    '1f30baae-c6b5-403b-855d-6cf9d7040650'):
            text = text.replace(old, 'a824008e-cf43-4287-84f8-4e930fa41a06')
        text = text.replace("review['boot_dtb_only_parent_az_interconnect_tag_delta']",
                            "review['boot_dtb_exact_parent_ba']")
        text = text.replace("review['native_cases_verified'] == 38",
                            "review['pas_diagnostic_native_checks'] == 91 and "
                            "review['pas_diagnostic_negative_controls'] == 5")
        if name in ('prepare-ba-runtime.py', 'deploy-ba.py'):
            old = "    cmdline = parent['cmdline'].replace('spx_attempt=20261004ba', 'spx_attempt=20261004bb')"
            assert text.count(old) == 1
            text = text.replace(old, old + " + ' qcom_scm.spx_pas_diag=1'")
        if name == 'prepare-ba-runtime.py':
            old = "            ('extra-option', dict(cmdline=expected + ' unexpected=1'))]:"
            assert text.count(old) == 1
            text = text.replace(old, "            ('extra-option', dict(cmdline=expected + ' unexpected=1')),\n"
                "            ('missing-pas-diag', dict(cmdline=expected.replace(' qcom_scm.spx_pas_diag=1', ''))),\n"
                "            ('disabled-pas-diag', dict(cmdline=expected.replace('qcom_scm.spx_pas_diag=1', 'qcom_scm.spx_pas_diag=0'))),\n"
                "            ('duplicate-pas-diag', dict(cmdline=expected + ' qcom_scm.spx_pas_diag=1'))]:")
            text = text.replace('identity_negative_cases=len(rejected),',
                "identity_negative_cases=len(rejected), pas_diagnostic_selector='qcom_scm.spx_pas_diag=1',")
        if name == 'deploy-ba.py':
            text = text.replace("== {'spx_attempt=20261004bb'}",
                "== {'spx_attempt=20261004bb', 'qcom_scm.spx_pas_diag=1'}")
            old = "    entry = entry.replace('AZ VIDEOCC and Iris1 startup', 'BB ICC and Iris1 startup')"
            assert old in text
            text = text.replace(old,
                "    inherited_cmdline = parent['cmdline'].replace('spx_attempt=20261004ba', 'spx_attempt=20261004bb')\n"
                "    entry = entry.replace(' ' + inherited_cmdline + '; then', ' ' + cmdline + '; then')\n"
                "    entry = entry.replace('BA ICC and Iris1 startup', 'BB PAS diagnostic and Iris1 startup')")
            text = text.replace('media_short_requested=True,',
                'media_short_requested=True, pas_diagnostics_requested=True,')
        if name == 'review-ba-preparation.py':
            text = text.replace("preserving AY's actual return", "preserving BA's actual return")
        if name == 'ba_boot_guard.py':
            text = text.replace('# Record the diagnosed legacy recovery-kernel startup failure. The fresh',
                '# Record the actual legacy recovery-kernel touch state. The fresh')
        ast.parse(text)
        assert not (SRC / target).exists(), target
        pending[target] = text
    assert len(pending) == 15
    for name, text in pending.items():
        with (SRC / name).open('x') as stream:
            stream.write(text)
    print('Created and parsed 15 distinct BB helpers; no installation')


if __name__ == '__main__':
    main()
