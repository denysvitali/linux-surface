#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Guard against rewriting a configured radio or changing its power preference."""
import unittest
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
