# Watchdog-guarded SPX kexec test loop

This is the proposed way to test successive mainline kernels without asking
for a firmware reboot each time. It is **not enabled yet**. The one-time reset
proof below must succeed before any mainline image is loaded.

## Why this avoids the failed path

An ARM64 `kexec` loads the raw Linux `Image`, initramfs and DTB from a running
known-good kernel, quiesces devices and enters the Image header directly. It
does not call the PE/COFF EFI-stub entry point and therefore does not repeat the
unprotected firmware/ExitBootServices path where the diagnostic boots hung.

The known-good guardian boot uses the already validated `.dtb.wdt` payload.
systemd 261 supports `KExecWatchdogSec=` and explicitly leaves the watchdog
armed when it executes kexec. The Qualcomm driver has no shutdown callback and
does not request `watchdog_stop_on_reboot()`. The next kernel's driver detects
an already-running APSS watchdog, reprograms it and marks it hardware-running;
`RuntimeWatchdogSec=30s` then keeps it fed. A lockup between kernels therefore
has a 30-second hardware reset path to the unchanged `spx-known-good` default.

The deployed 6.18 guardian DTB uses its tree's older
`qcom,apss-wdt-sm8150` fallback compatible, while the mainline target uses the
new binding's `qcom,apss-wdt-sc8180x`; both pair it with `qcom,kpss-wdt` and
map the same audited `0x17c10000` hardware. The 6.18 config also lacks watchdog
sysfs attributes, so the live guard identifies its bound driver through the
platform-driver symlink when `identity` is absent.

Official references:

- [systemd `KExecWatchdogSec=` documentation](https://github.com/systemd/systemd/blob/main/man/systemd-system.conf.xml)
- [systemd shutdown keeps the watchdog armed](https://github.com/systemd/systemd/blob/main/src/shutdown/shutdown.c)
- [Linux ARM64 Image boot protocol](https://docs.kernel.org/arch/arm64/booting.html)
- [Linux kexec/kdump documentation](https://docs.kernel.org/admin-guide/kdump/kdump.html)

## One-time supervised proof

1. Keep `saved_entry=spx-known-good`, an empty `next_entry`, and no EFI
   `BootNext`. Never change the persistent recovery default.
2. With the user available to power-cycle once if necessary, select the
   known-good 6.18 kernel with the structurally verified `.dtb.wdt`. This is
   the only firmware reboot the loop needs.
3. Configure both `RuntimeWatchdogSec=30s` and `KExecWatchdogSec=30s`, re-enter
   the manager, and verify `/dev/watchdog0`, Qualcomm identity, PID 1 ownership
   and both effective 30-second values.

The repository's `90-spx-kexec-watchdog.conf` is the drop-in for the second
setting. Installing it is harmless on the current watchdog-less recovery boot;
it becomes effective when PID 1 starts on the guardian boot.
4. First kexec the same known-good kernel and `.dtb.wdt` through the file-based
   syscall. Verify a new boot ID, successful root mount, and watchdog adoption.
   This proves the normal handoff without involving a mainline kernel.

The exact control payload is pinned by `guardian-kexec-20260915.json`; it is a
raw decompression of the installed recovery kernel plus byte-identical copies
of its initramfs and the already validated watchdog DTB.

The first control on 2026-09-15 deliberately selected the legacy
`kexec_load(2)` path (`kexec --kexec-syscall`). It did not reach the target
kernel. The shutdown journal ended after PID 1 armed `qcom_wdt` for 30 seconds;
the next boot had a new boot ID, initialized EFI again, and used the unchanged
`spx-known-good` GRUB default. This proves automatic recovery after the failed
post-Linux handoff, but also disqualifies the legacy loader on this device.

The same pinned control payload was subsequently loaded and unloaded, without
execution, through `kexec_file_load(2)` (`kexec --kexec-file-syscall`). Both
operations succeeded on the safe boot. Execution was then attempted from a
fresh watchdog guardian. It also failed to reach the known-good target; the
watchdog again reset the machine through firmware to `spx-known-good`, without
manual intervention. The exact boot IDs and observations are recorded in
`kexec-runtime-20260915.json`.

Consequently, automatic recovery after ExitBootServices is proven, but neither
Linux kexec loader is a usable test transport on this device. The manifests
retain `loader: kexec_file_load` to reject the already worse legacy route, but
the guard's read-only pass is not authorization to execute either loader.
Mainline execution remains prohibited until a different protected transport is
independently validated.

`build-kexec-hang.py` emits the fixed 4 KiB payload without a toolchain. Its
five instruction words are documented in `kexec-hang.S`, checked byte-for-byte
by the unit suite, and disassemble as `b 0x40`, `nop`, `msr daifset,#0xf`,
`wfe`, and a branch back to `wfe`. Building it does not load or queue it.

The observed resets directly cover loss of progress after the original
successful ExitBootServices and after the kexec handoff. They do not make
experimental EFI boots safe, and the failed controls do not authorize kexec.

## If a future protected transition is validated

Use a raw, verified ARM64 `Image` (not the EFI `vmlinuz`), a matching initramfs
and a DTB containing `watchdog@17c10000`. Pin all three SHA-256 values and the
exact command line in a schema-1 JSON manifest. Run `kexec-guard.py --offline`
while staging and run it again without `--offline` immediately before loading.
The checker is read-only and deliberately has no load/execute option.

The installed `/boot/vmlinuz-spx-next-test` and
`sc8180x-surface-pro-x-next-test.dtb` currently do **not** match the clean
2026-09-15 build; the installed DTB lacks the watchdog node. They must not be
used for this loop. A matching raw Image, freshly generated initramfs and DTB
are staged under `/var/lib/spx-kexec/7.3.0-rc2-spx-next-test+`; their hashes are
pinned by `mainline-kexec-20260915.json`. `/boot` is full, but kexec reads the
payload while the current root is mounted and does not require it on `/boot`.

Do not execute the current mainline payload through kexec. If another protected
transition is independently validated, collect the component matrix after each
successful boot while preserving the known-good GRUB default.

## Offline deployment status (2026-09-15)

- The systemd drop-in is installed at
  `/etc/systemd/system.conf.d/90-spx-kexec-watchdog.conf`. Both guardian boots
  reported effective 30-second runtime and kexec watchdog values.
- The mainline Image, newly generated matching initramfs and watchdog DTB pass
  `kexec-guard.py --offline` from the committed manifest.
- The clean 185-module tree is installed at
  `/usr/lib/modules/7.3.0-rc2-spx-next-test+`. The previous same-release tree is
  preserved at `/var/lib/spx-boot-diagnostics/module-backups/` with the suffix
  `-pre-kexec-20260915`.
- The fixed hang payload is staged under
  `/var/lib/spx-kexec/recovery-validation`, but nothing is loaded in the kexec
  slot. Its SHA-256 is
  `f1480f9bcc94113f080a3576883159fad07f214a528cb5ff10ff4d24f407d9f7`.
- The dedicated hang payload was not needed: two real known-good control
  handoffs failed and independently demonstrated the watchdog reset path.
- The pre-existing `/boot` filesystem is full. A failed distinct staging copy
  created one partial and three empty files; only that new `/boot/spx-kexec`
  directory was removed. Existing boot files were not changed.
