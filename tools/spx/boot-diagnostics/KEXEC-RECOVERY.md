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
4. First kexec the same known-good kernel and `.dtb.wdt`. Verify a new boot ID,
   successful root mount, and watchdog adoption. This proves the normal handoff
   without involving a mainline kernel.
5. Record boot ID, monotonic/realtime timestamps, hashes, GRUB state and a
   unique nonce, sync them to disk, then kexec `kexec-hang.Image`. This tiny
   audited ARM64 payload masks exceptions and waits forever after Linux's kexec
   shutdown. Do not touch the device for 60 seconds.
6. A watchdog reset must return through firmware and GRUB into
   `spx-known-good` without user input. Accept the proof only if the new boot
   time falls inside the recorded watchdog window and the nonce is consumed
   once. Any manual intervention, ambiguous timing or missing record is a
   failure and keeps experimental kexec disabled.

`build-kexec-hang.py` emits the fixed 4 KiB payload without a toolchain. Its
five instruction words are documented in `kexec-hang.S`, checked byte-for-byte
by the unit suite, and disassemble as `b 0x40`, `nop`, `msr daifset,#0xf`,
`wfe`, and a branch back to `wfe`. Building it does not load or queue it.

This test directly covers loss of progress after the original successful
ExitBootServices and after the kexec handoff. It does not make experimental EFI
boots safe; those remain prohibited. It authorizes only the kexec path.

## Every mainline transition

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

After each successful mainline boot, collect the component matrix before the
next kexec. If the kernel locks, the watchdog returns to the known-good GRUB
default. If a normal test finishes, it can kexec directly to the next candidate
or to the known-good guardian, so firmware reboots are no longer part of the
ordinary edit/build/test cycle.

## Offline deployment status (2026-09-15)

- The systemd drop-in is installed at
  `/etc/systemd/system.conf.d/90-spx-kexec-watchdog.conf`. The current manager
  still reports `KExecWatchdogUSec=0`; the 30-second value will be read by the
  next guardian boot. No manager re-exec or reboot was requested during setup.
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
- The pre-existing `/boot` filesystem is full. A failed distinct staging copy
  created one partial and three empty files; only that new `/boot/spx-kexec`
  directory was removed. Existing boot files were not changed.
