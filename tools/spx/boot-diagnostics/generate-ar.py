#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Retain AQ's strict actual baseline and fallback, with AR identity/module counts."""
import ast
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent


def identity(text):
    for before, after in (('20261003aq', '20261003ar'), ('spx-aq-', 'spx-ar-'),
                          ('aq_boot_guard', 'ar_boot_guard'), ('aq-', 'ar-')):
        text = text.replace(before, after)
    text = re.sub(r'\bAQ\b', 'AR', text)
    # Exact module-tree count changes only; acceptance expressions are preserved.
    return re.sub(r'\b202\b', '208', text)


if __name__ == '__main__':
    for old in ('aq-finalize.py', 'review-aq-result.py', 'aq-return.py',
                'aq-camera-provider.py', 'review-aq-camera-provider.py'):
        new = old.replace('aq-', 'ar-')
        path = SRC / new
        assert not path.exists(), new
        text = identity((SRC / old).read_text())
        ast.parse(text)
        path.write_text(text)
    print('AR baseline, provider collector/reviewer and fallback generated without changing criteria')
