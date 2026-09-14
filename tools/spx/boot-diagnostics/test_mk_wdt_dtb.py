#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exercise the DTB patcher against a synthetic base and its refusals."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('mk-wdt-dtb.py')

spec = importlib.util.spec_from_file_location('mk_wdt_dtb', SCRIPT)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

BASE = '''/dts-v1/;

/ {
	#address-cells = <0x02>;
	#size-cells = <0x02>;

	clocks {
		sleep-clk {
			compatible = "fixed-clock";
			#clock-cells = <0x00>;
			clock-frequency = <0x7ffc>;
			clock-output-names = "sleep_clk";
			phandle = <0x2c>;
		};
	};

	soc@0 {
		mailbox@17c00000 {
			compatible = "qcom,sc8180x-apss-shared";
			reg = <0x00 0x17c00000 0x00 0x1000>;
			#mbox-cells = <0x01>;
			phandle = <0x2a>;
		};

		timer@17c20000 {
			compatible = "arm,armv7-timer-mem";
			reg = <0x00 0x17c20000 0x00 0x1000>;
		};
	};
};
'''


class PatcherTests(unittest.TestCase):
    def build(self, tmp, source):
        dtb = Path(tmp) / 'base.dtb'
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(dtb),
                        '-'], input=source, text=True, check=True,
                       capture_output=True)
        return dtb

    def decompile(self, dtb):
        return subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', str(dtb)],
                              text=True, capture_output=True, check=True).stdout

    def run_patcher(self, base, out):
        return subprocess.run(['python3', str(SCRIPT), '--base', str(base),
                               '--out', str(out)],
                              text=True, capture_output=True)

    def test_node_is_added_under_soc_with_the_sleep_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.dtb'
            result = self.run_patcher(self.build(tmp, BASE), out)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = self.decompile(out)
            self.assertIn('watchdog@17c10000', text)
            self.assertIn('qcom,apss-wdt-sm8150', text)
            self.assertIn('clocks = <0x2c>;', text)
            # It must land inside soc@0, not at the root.
            soc = text[text.index('soc@0 {'):]
            self.assertIn('watchdog@17c10000', soc)

    def test_missing_anchor_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.dtb'
            result = self.run_patcher(
                self.build(tmp, BASE.replace('mailbox@17c00000', 'mailbox@deadbeef')),
                out)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('anchor', result.stderr)
            self.assertFalse(out.exists())

    def test_unlabelled_sleep_clock_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.dtb'
            result = self.run_patcher(
                self.build(tmp, BASE.replace('\t\t\tphandle = <0x2c>;\n', '')), out)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('phandle', result.stderr)

    def test_base_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.build(tmp, BASE)
            original = base.read_bytes()
            result = self.run_patcher(base, base)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(base.read_bytes(), original)

    def test_existing_symlink_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.build(tmp, BASE)
            out = Path(tmp) / 'out.dtb'
            target = Path(tmp) / 'missing.dtb'
            out.symlink_to(target)
            result = self.run_patcher(base, out)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(out.is_symlink())
            self.assertFalse(target.exists())

    def test_second_application_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.dtb'
            second = Path(tmp) / 'second.dtb'
            self.assertEqual(self.run_patcher(self.build(tmp, BASE), out).returncode, 0)
            self.assertNotEqual(self.run_patcher(out, second).returncode, 0)
            self.assertFalse(second.exists())

    def test_wrong_property_with_same_line_count_is_rejected(self):
        expected = patcher.insert(BASE, '0x2c')
        with self.assertRaises(SystemExit):
            patcher.validate_result(expected, expected.replace('clocks = <0x2c>',
                                                               'clocks = <0x2d>'))

    def test_publish_race_preserves_destination_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self.build(tmp, BASE)
            out = Path(tmp) / 'out.dtb'
            out.write_bytes(b'existing recovery artifact')
            before = set(Path(tmp).iterdir())
            with self.assertRaises(FileExistsError):
                patcher.publish(candidate, out)
            self.assertEqual(out.read_bytes(), b'existing recovery artifact')
            self.assertEqual(set(Path(tmp).iterdir()), before)


if __name__ == '__main__':
    unittest.main()
