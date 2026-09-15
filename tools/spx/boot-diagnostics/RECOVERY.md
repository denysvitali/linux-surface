# Required recovery before further SPX hardware boot tests

Experimental reboots are blocked until recovery covers EFI stub execution,
ExitBootServices, early kernel initialization and userspace without requiring a
manual restart. Build success and isolated successful boots do not meet this
requirement. There is deliberately no command-line bypass in preflight.py.

## Established facts

- The recovery kernel is 6.18.3-1-surface+, selected by spx-known-good.
- Neither deployed test nor recovery DTB declares a hardware watchdog. The
  recovery sysfs watchdog class is empty. A diagnostic journal reports:
  `Failed to open any watchdog device before the initial transaction completed`.
- QCOM_WDT=y was mistaken for watchdog protection. Registering the driver alone
  does not instantiate or arm a watchdog.
- return.timer requires userspace; panic and soft-lockup settings require Linux
  to execute the corresponding handling code. Neither protects an EFI hang.
- UEFI SetWatchdogTimer is disabled by a successful ExitBootServices call. It
  may also be implemented in software. It cannot alone cover the whole boot.
  See [UEFI Boot Services](https://uefi.org/specs/UEFI/2.10_A/07_Services_Boot_Services.html#efi-boot-services-setwatchdogtimer)
  and [barebox EFI watchdog documentation](https://www.barebox.org/doc/latest/boards/efi.html#uefi-watchdog).
- EFI Boot Guard can arm hardware before OS loading, but its published drivers
  do not include a Qualcomm-specific driver. WDAT support is not evidence that
  this Surface firmware provides WDAT. Its ACPI tables are not exposed in this
  DT recovery boot; a read-only firmware-table read was denied. No table or
  hardware address should be guessed. See [EFI Boot Guard](https://github.com/siemens/efibootguard).

## Pre-kernel watchdog candidate (2026-09-14) — prepared, NOT validated

The platform watchdog the section above asks for is now identified, and it is
not a guess: this device has driven it before.

- `Documentation/devicetree/bindings/watchdog/qcom-wdt.yaml` lists
  `qcom,apss-wdt-sc8180x`. Commit `26d14b9fc341` added it together with
  `qcom,apss-wdt-sc8280xp`, but only `sc8280xp.dtsi` ever received a node.
  `sc8180x.dtsi` has no watchdog, so the mainline port never probed one.
- `sc7180.dtsi` and `sc8280xp.dtsi` place it at `0x17c10000` with
  `qcom,kpss-wdt`, `clocks = <&sleep_clk>` and `GIC_SPI 0`. `sc8180x.dtsi` has
  a hole at exactly that address, between `apss_shared@17c00000` and
  `timer@17c20000`. `sleep_clk` is 32764 Hz.
- The Surface 6.18 tree's speaker DTBs carried this exact node, and
  `scripts/spx-speakers-up.sh` refuses to continue unless `/dev/watchdog0`
  exists, PID 1 owns it and `RuntimeWatchdogUSec` is 30s. Those guarded runs
  reached playback, so the hardware has already produced a working watchdog on
  this device.

Added to the mainline port: `watchdog@17c10000` in `sc8180x.dtsi`
(`qcom,apss-wdt-sc8180x`, `qcom,kpss-wdt`). The DTB builds and `CHECK_DTBS`
reports no schema warning for the node; 40 warnings elsewhere in this
downstream DT are pre-existing.

The kernel driver only arms the watchdog once Linux runs, which is too late for
the failures that created this lock: attempts 20260914-04 and 20260914-07 both
recorded GRUB `handoff-ready` and then produced no kernel log at all, so the
hang is in the EFI stub or before the console exists. Arming has to happen
before the OS.

Candidate mechanism: GRUB writes the registers itself. The installed GRUB 2.14
provides `memrw` with `read_dword`/`write_dword`.
`tools/spx/boot-diagnostics/wdt.py` renders probe, arm and disarm snippets from
the driver's own arithmetic (bark `(timeout-1)*rate`, bite `timeout*rate`, enable
bit last); `test_wdt.py` checks the arithmetic, the 20-bit bite limit and GRUB
syntax, and passes.

**Not established:** that a GRUB write reaches `0x17c10000` on this device. On
arm64 GRUB runs on the firmware's page tables; an unmapped access faults and
GRUB has no handler, so it would hang until the user interrupts. That question
is what stage 0 below answers, and until it is answered the reboot lock stays.

### Staged validation

| Stage | Content | Risk |
| --- | --- | --- |
| 0a | `lsefimmap` from the GRUB menu; confirm a descriptor covers `0x17c10000`. | None; produces no writes. |
| 0b | Run the generated probe snippet. It only prints `WDT_EN`/`WDT_STS`; record the screen manually because GRUB `read_dword` does not assign variables. | A fault hangs at the menu and needs a power cycle. Nothing is armed, so there is no reset loop. |
| 1 | Boot the known-good kernel with a DTB carrying the node; confirm `/dev/watchdog0`, PID 1 ownership and a 30s runtime watchdog. | Known-good boot only; no experimental kernel. |
| 2 | Arm in the test entry and disarm in the recovery entry, then one experimental boot. | The test that the lock exists to gate. |

Stage 1 needs a known-good DTB plus exactly one node. Rebuilding from the 6.18
worktree does not give that — the tree has moved on since
`sc8180x-surface-pro-x.dtb.wsa` was deployed and a fresh build differs by over a
thousand lines. `mk-wdt-dtb.py` patches the deployed binary instead and then
proves the result by decompiling both and diffing the text; it refuses to write
output unless the only change is the added node.

Stages 0a/0b are read-only and can run against the default entry. Nothing may be
armed until stage 0b has succeeded, and the lock is lifted only after a
deliberate hang resets into the unchanged recovery default.

### Stage 1 validated on the current known-good boot (2026-09-15)

The current boot proves the stage-1 payload and runtime path, although the
historical action that selected the payload was not recorded:

- `/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.wdt`, sha256
  `5ada4b8d7f9dd3139e1466c1339b3377480a8fc9b24d639f6ab604cc2602bc37`.
  Decompiling it next to the deployed `sc8180x-surface-pro-x.dtb.wsa`
  (`1ef46c32dde4…`) shows exactly one added node and no other difference.
- Sorting and decompiling the live `/proc/device-tree` and `.dtb.wdt` produces
  exactly one diff hunk: the EFI stub's six additions under `/chosen`
  (`bootargs` plus five UEFI memory-map/system-table properties). All other
  nodes and properties, including `watchdog@17c10000`, match. The `.dtb.wsa`
  comparison has a second hunk for the missing watchdog node.
- Boot `40bc7e68-538d-4c15-a39d-84158efe9e6a` is running the known-good
  `6.18.3-1-surface+` kernel. Its journal shows `qcom_wdt` active in the
  initramfs and host, systemd owns `/dev/watchdog0`, and the configured runtime
  timeout is 30 seconds. This validates stage 1 without an additional reboot.
- A second entry, `spx-known-good-wdt`, in `/boot/grub/grub.cfg`. Against
  `spx-known-good` it differs in the title/`--id` line and the `devicetree`
  path only; kernel, command line and initramfs are byte-identical.
  `grub-script-check` passes. `/boot/grub/grub.cfg.bak-stage1-wdt` is the
  pre-change copy.
- `check-wdt-stage1.sh` prints the live node, `watchdog0`, PID 1 ownership and
  the 30-second hardware-watchdog journal messages on the current boot.

`qcom_wdt` is already in `/etc/mkinitcpio.conf` `MODULES`, so it loads from the
initramfs, and `/etc/systemd/system.conf.d/90-spx-watchdog.conf` already asks
for a 30s runtime watchdog. Only the device tree node was missing.

`next_entry` is empty and the persistent default remains `spx-known-good`; the
deployed `.dtb.wsa` is untouched. Because the two stage-1 menu entries use the
same kernel command line, the live state cannot reconstruct which historical
GRUB selection loaded the matching payload. That uncertainty does not require
another stage-1 reboot, but it also supplies no evidence for stages 0a, 0b or 2.

## Work needed before lifting the block

Identify a documented, accessible platform watchdog and a bootloader path that
arms it before the OS. Verify that firmware handoff does not disable the same
hardware, that the kernel adopts/feeds it correctly, and that expiration forces
reset to the unchanged recovery default. Confirm the actual timeout and reset
cause. Cover loss of progress both before and after ExitBootServices.

Validation itself needs an independent recovery route so a failed watchdog test
does not again require the user to restart this device. An external controller
must be able to force reset or operate the power button; merely removing USB-C
power is insufficient for a battery-powered Surface. No such route is currently
established. Offline development can continue; experimental hardware boots cannot.

## Deployed protection and evidence

The active GRUB configuration exposes the verified recovery entry and firmware
settings. Experimental generators and custom entries are disabled. Original
configs, generator permissions and artifact hashes are preserved in the root-only
`/var/lib/spx-boot-safety/20260914-unprotected-boot-lock` archive.
`preflight.py --reboot` exits before reading an attempt or issuing any command.
Tests cover this refusal even with valid artifacts and with an invalid manifest.
Local AGENTS.md files record the user's boot prohibition for future sessions.
These controls prevent this test workflow from repeating an unprotected boot;
they are not a claim that automatic early-boot recovery has been implemented.
