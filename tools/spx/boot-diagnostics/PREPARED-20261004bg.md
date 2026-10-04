# BG: Bluetooth setup and non-audio functional checks

The mainline candidate is installed but has not been selected or booted yet.
Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`; build directory:
`/var/tmp/spx-mainline-trial-20261004bg/work-build`. Keep both for subsequent
incremental/module tests. The completed Image, DTB and modules link successfully;
normal modules_install, depmod and mkinitcpio complete.

The functional change is the installation's Bluetooth address in the copied
boot DTB. The 6.18 tree documents why it is needed; the recovery controller
appears and starts discovery after supplying it. No factory address is claimed.
Mainline pairing/peripheral use are still pending. Venus is parked and the
shared UC trial stays disabled.

Speaker/WCD/SoundWire modules are excluded from the manual initramfs list and
blocked by the kernel command line for this non-audio session. No sound,
amplifier-power test, microphone or camera capture is scheduled.

The single [trial tool](../trial.py) is committed as `64d48119f4cd`; its generic
return units pass systemd verification and have the correct attempt argument.
The timer is enabled for900s after boot. Old diagnostic timers do not match
the new `spx_boot=mainline-functional` command line. Known-good stays the
persistent default and the pending selection is empty. Two completed old boot
directories have been preserved off the EFI partition to provide space.

Current recovery boot: `42966575-e6ec-4698-83c2-80e5aeb07011`, kernel
`6.18.3-1-surface+`. The handoff tool will recheck its identity and recovery
kernel/initramfs/DTB, select BG once and immediately recheck pending/default
state before reboot. Early-kernel automatic recovery remains unvalidated.

Next: actual mainline Bluetooth setup/discovery, battery and sensors, Wi-Fi,
thermal/runtime power and firmware-service observations. A
[hands-on session](PHYSICAL-TESTS.md) has been requested for physical features.
No hardware acceptance box is closed by preparation. Actual BF remains the
latest completed mainline result.

State and eventual logs: `/var/lib/spx-boot-diagnostics/functional/20261004bg/`.
