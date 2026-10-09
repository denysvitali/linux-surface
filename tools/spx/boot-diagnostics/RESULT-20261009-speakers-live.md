boxes closed: 3 of 47; newly closed: none.

# Speakers: saved blacklist corrected; live loading still blocked

Boot: `29923cc8-d3dd-4fd6-8400-e73cfbe6b5ca`.
Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`.

**Request/change:** fix speakers without rebooting. Stopped the active
`spx-trial-return@20261009fi.timer`; both timer and return service are inactive.
Corrected the saved FI GRUB entry and its preparation settings to allow audio
drivers with both amplifiers parked (`spx_audio=parked`, GPIO value 0x18).
The trial generator now removes inherited audio blacklist entries for
`--audio`, preserving unrelated restrictions. No kernel change, successful
driver load, speaker power or microphone capture performed.

**Observed:** only the dock USB sound card is registered. The kernel command
line and `/sys/module/kernel/parameters/module_blacklist` both list
`wcd934x,soundwire_qcom,snd_soc_wsa881x,snd_soc_wcd934x`. All four modules are
absent. This boot's kernel log explicitly rejects all four; the delayed audio
loader failed with `Operation not permitted`.

**Meaning:** this is a kernel loader restriction, before any codec playback
code runs. `kernel/module/main.c` declares the blacklist with mode 0400 and
rejects matching module names with `-EPERM`. `kernel/params.c` installs no
store callback for read-only parameters, so chmod is not a live override.
Normal modprobe/insmod cannot load these drivers on this boot. Existing
6.18 stereo findings and CB/DE/DG results were reviewed; they do not resolve
the separate playback-reopen defect or this boot's loading restriction.

**User-requested retry:** same boot and live blacklist. Explicit root
`modprobe wcd934x` with amplifier enables parked returned `Operation not
permitted`; fresh dmesg at uptime 2188.922407 states `Module wcd934x is
blacklisted`. No driver loaded or playback ran. Return timer remains inactive.

**Validation/next:** all 60 audio orchestration tests succeeded, including
blacklist removal and parked startup settings. GRUB syntax validated; no next
boot selected and known-good remains default. The live blacklist is unchanged
and this kernel has no livepatch support. The saved correction needs a later
boot; none was requested. Stop under the no-reboot instruction; A01–A03 remain
open. A device-lock acquisition failed during the configuration update but the
shell continued; no hardware test ran. Subsequent check found both locks free.
