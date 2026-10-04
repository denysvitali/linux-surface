# BJ: parked audio startup installed, not yet booted

BI remains live on boot `84e729fc-a68c-4720-a6f0-042acf60f604`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. Touch, pen, keyboard and Bluetooth work
according to the user. Internal speakers are blacklisted on BI; the blacklist
requires a new boot to remove. No amp power or playback ran during preparation.

BJ keeps that kernel release, Image, DTB configuration and Bluetooth address.
Only WCD and Qualcomm SoundWire modules changed (`5f0155537be2`, `257e18beb01b`),
rebuilt incrementally in the existing BG build directory. The GPIO override
explicitly manages mask `0x1e`, direction `0x1e`, output `0x18`: both amplifier
enable pins start low. A driver-owned snapshot exposes native physical IDs,
frame state and GPIO readback without the old helpers' copied private structs.

The generic trial tool now prepares from a collected mainline boot and can
replace the two blacklisted, unloaded modules while preserving running modules.
BJ disables automatic desktop audio and legacy speaker bridges using a condition
specific to `spx_audio=parked`. The known-good persistent default and generic
900-second return/check timers remain in use. Installation passed, only the two
unloaded modules were replaced, and no one-shot is selected. BI's current return
remains due at **18:32:53 CEST on October 4**. Do not select BI again.

The next proposed run is amplifier initialization only: hold the discovered
SoundWire master awake, release pin 1 and require unit 3, then release pin 2 and
require distinct units 3/4. Each stage gets a five-second polling budget. Always
attempt to park both amps and verify physical readback before restoring runtime
PM or previously active audio. The test opens no PCM and captures nothing.
Power-up has previously emitted static; this run requires explicit authorization.
The PM hold is `713ae79d5d64`; `07d79076f427` handles systemctl's blank record
separators in the desktop-audio preflight. The shared build/release is unchanged.

Validation: two-module incremental build, module dependency check, initramfs
generation, GRUB syntax, parked command-line settings, Python syntax and offline
plan passed. State is in `/var/lib/spx-boot-diagnostics/functional/20261004bj/`.
This is preparation, not functional audio evidence. A01 remains open. Fresh
late initialization and playback still need porting after native enumeration.
