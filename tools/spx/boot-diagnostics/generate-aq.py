#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Retain AP's strict baseline collector/reviewer and fallback with AQ identity."""
import ast
from pathlib import Path
import re

SRC = Path(__file__).resolve().parent


def identity(text):
    for before, after in (
        ('20261002ap', '20261003aq'), ('20261001am', '20261003aq'),
        ('spx-ap-', 'spx-aq-'), ('ap_boot_guard', 'aq_boot_guard'),
    ):
        text = text.replace(before, after)
    return re.sub(r'\bAP\b', 'AQ', text)


def main():
    for old, new in [('ap-finalize.py', 'aq-finalize.py'),
                     ('review-ap-result.py', 'review-aq-result.py'),
                     ('ap-return.py', 'aq-return.py')]:
        path = SRC / new
        assert not path.exists(), new
        transformed = identity((SRC / old).read_text())
        ast.parse(transformed)
        path.write_text(transformed)
    print('AQ baseline collector/reviewer and fallback generated; only identity changes')


if __name__ == '__main__':
    main()
