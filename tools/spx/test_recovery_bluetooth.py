#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Guard against rewriting a configured radio or changing its power preference."""
import runpy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import recovery_bluetooth as repair

MISSING = '''Extended index list with 1 item
Unconfigured controller (hci0,UART)
hci0: Unconfigured controller
    manufacturer 29
    supported options: public-address
    missing options: public-address
'''


class Guards(unittest.TestCase):
    def test_lock_directory_follows_relocated_helper(self):
        with TemporaryDirectory() as directory:
            relocated = Path(directory) / 'recovery.py'
            relocated.write_text(Path(repair.__file__).read_text())
            namespace = runpy.run_path(str(relocated))
            self.assertEqual(namespace['PRIVATE'], relocated.parent)

    def test_restores_original_rfkill_even_when_repair_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, kind, label, state in [('rfkill0', 'wlan', 'phy0', '0'),
                                             ('rfkill1', 'bluetooth', 'hci0', '0')]:
                entry = root / name
                entry.mkdir()
                for file, value in [('type', kind), ('name', label), ('soft', state)]:
                    (entry / file).write_text(value)
            with patch.object(repair, 'RFKILL', root):
                for original in ('0', '1'):
                    soft = root / 'rfkill1' / 'soft'
                    soft.write_text(original)
                    with self.assertRaisesRegex(RuntimeError, 'repair failed'):
                        with repair.blocked_controller():
                            self.assertEqual(soft.read_text().strip(), '1')
                            self.assertEqual((root / 'rfkill0' / 'soft').read_text(), '0')
                            raise RuntimeError('repair failed')
                    self.assertEqual(soft.read_text().strip(), original)

    def test_waits_for_management_enumeration(self):
        with patch.object(repair.subprocess, 'check_output', side_effect=[
                'Extended index list with 0 items', MISSING]), \
             patch.object(repair.time, 'sleep') as wait:
            self.assertEqual(repair.controller_info(), MISSING)
            wait.assert_called_once_with(.25)

    def test_only_fitted_unconfigured_uart_is_eligible(self):
        self.assertTrue(repair.missing_address(MISSING))
        for text in (MISSING.replace('UART', 'USB'), MISSING.replace('manufacturer 29', 'manufacturer 42'),
                     MISSING.replace('missing options: public-address', 'missing options:'),
                     MISSING.replace('Unconfigured controller (hci0,UART)', 'Primary controller (hci0,UART)')):
            self.assertFalse(repair.missing_address(text))

    def test_already_configured_controller_performs_no_writes(self):
        def path(name):
            p = Mock()
            p.read_text.return_value = 'spx_boot=known-good'
            p.read_bytes.return_value = b'Microsoft Surface Pro X (SQ2)\0'
            return p
        with patch.object(repair, 'Path', side_effect=path), \
             patch.object(repair.subprocess, 'check_output', return_value='Primary controller (hci0,UART)'), \
             patch.object(repair.subprocess, 'run') as action:
            repair.main()
            action.assert_not_called()

    def test_address_validation_rejects_shared_invalid_defaults(self):
        for value in ('', '00:00:00:00:00:00', 'FF:FF:FF:FF:FF:FF', '01:02:03:04:05:06'):
            with self.assertRaises(RuntimeError):
                repair.validate_address(value)


if __name__ == '__main__':
    unittest.main()
