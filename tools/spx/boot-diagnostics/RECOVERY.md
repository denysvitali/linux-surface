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
