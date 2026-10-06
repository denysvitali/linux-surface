import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import pmic_rtc


class Staging(unittest.TestCase):
    def test_preserves_system_clock_alias_and_uses_only_alarm_candidate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dtb = root / 'board.dtb'
            subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb', '-o', str(dtb)],
                           input='''/dts-v1/; / {
                model = "Microsoft Surface Pro X (SQ2)";
                aliases { rtc0 = "/surface-clock"; };
                surface-clock { compatible = "test,clock"; };
                soc@0 { spmi@c440000 { pmic@0 {
                    compatible = "qcom,pm8150", "qcom,spmi-pmic";
                }; }; }; };
                ''', text=True, check=True)
            pmic_rtc.stage(dtb)
            def get(node, prop):
                return subprocess.check_output(['fdtget', '-t', 's', str(dtb), node, prop], text=True).strip()
            self.assertEqual(get('/aliases', 'rtc0'), '/surface-clock')
            self.assertEqual(get('/aliases', 'rtc1'), pmic_rtc.NODE)
            props = subprocess.check_output(['fdtget', '-p', str(dtb), pmic_rtc.NODE], text=True).splitlines()
            self.assertEqual(set(props), {'compatible', 'reg', 'reg-names', 'interrupts'})
            pmic_rtc.stage(dtb)
            subprocess.run(['fdtput', '-t', 'x', str(dtb), pmic_rtc.NODE, 'interrupts',
                            '0', '62', '1', '1'], check=True)
            with self.assertRaises(AssertionError):
                pmic_rtc.stage(dtb)

    def test_ioctl_layout_matches_linux_headers(self):
        with TemporaryDirectory() as directory:
            binary = Path(directory) / 'rtc-abi'
            subprocess.run(['cc', '-x', 'c', '-', '-o', str(binary)], input='''
                #include <linux/rtc.h>
                #include <stdio.h>
                int main(void) { printf("%lx %lx %lx %lx %zu %zu\\n",
                    (unsigned long)RTC_RD_TIME, (unsigned long)RTC_WKALM_RD,
                    (unsigned long)RTC_WKALM_SET, (unsigned long)RTC_AIE_OFF,
                    sizeof(struct rtc_time), sizeof(struct rtc_wkalrm)); }
                ''', text=True, check=True)
            self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(),
                             '80247009 80287010 4028700f 7002 36 40')


if __name__ == '__main__':
    unittest.main()
