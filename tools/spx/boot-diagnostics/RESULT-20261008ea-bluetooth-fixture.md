# EA active discovery observes fresh reports; early WLAN check fails

**Change:** bcf927690d70 retains one active bluetoothctl process through normal
AC sleep. Actual EA boot701bb5d8-e4b3-4ac1-85cb-e8eea4ea2c31,
7.3.0-rc2-spx-mainline-20261004bg+; no kernel change, playback or capture.

**Observed:**29.0681s sleep passes RTC IRQ3->4/event, service/kernel/thaw proof.
Same scanner PID5801/startticks/pipe identities before/after;13 pre-sleep and3
post-drain fresh peers in5s windows.1327 queued bytes discarded to EAGAIN;
counts prove delivered reports after drain, not transmission timestamps.
New immediate full-radio snapshot rejects wlan0 before the existing bounded
native reconnection grace in infrastructure post-checks. Full result fails.

**Cleanup:** owned scanner stops/reaps, original radio off-blocked/soft1 actually
restores, masks/alarm/inhibitor/native closed PCMs/parked amps/FIFO0/PMauto
restore. Premature WLAN checks also leave scanner/fixture cleanup failures and
restored=false in the original report; preserve these. Later native WLAN
reconnects without intervention, original off/soft1 separately observed. No
acceptance box yet; no radio repair between discovery phases.
Evidence: functional/20261008ea/bluetooth-discovery-resume-wlan-order-failure/.

**Next:** immediate Bluetooth-only identity proof, stop/reap, then existing
infrastructure WLAN grace. Restore radio preference independently of WLAN;
require unchanged native connection after bounded observation. Commit/test
helper correction, then one changed same-boot test; no reboot needed.
