boxes closed: 3 of 47; newly closed: none.

# WX promoted to the persistent 7.x baseline

User requested 7.x as the normal baseline after finding 6.18 active again.
WX boot `11455cda-536d-4af7-bffe-7a17ce29650c` had verified native speaker
reopen and an active GNOME Wayland desktop on
`7.3.0-rc2-spx-mainline-20261004bg+`. The earlier reboot cause is unknown:
the available journal has no trial-return invocation. GRUB still defaulted
to 6.18, so any ordinary restart selected it.

**Changed:** promoted the existing verified WX kernel/initramfs/DTB into
`/boot/spx-mainline`. GRUB's persistent default and saved selection are now
`spx-mainline`; 6.18 remains a manual recovery entry. The console override
is absent. Disabled WX's trial return timer and added a baseline marker that
makes accidental trial-return calls stop without rebooting. Future trial
validation and returns recognize the promoted 7.x default. No new kernel
build, audio playback or capture was needed.

**Validation:** original boot payload checksums and GRUB syntax verified;
saved/default selections agree, with no one-shot pending selection. The
existing startup collection remains enabled; consumed microphone tests do
not repeat. Baseline policy is recorded in AGENTS.md and the trial README.

**Boot verification:** boot `c7ebfe0d-89ec-4a57-b24f-daa6a2d080ea` runs
7.3.0-rc2 from `/spx-mainline/vmlinuz`. GRUB default/saved selection agree
on `spx-mainline`, no one-shot selection is pending, and the return timer is
disabled/inactive with no expiry. GNOME Wayland is active on foreground VT2;
Mutter reports the display on. Startup collection completed on this boot.
Both native clock votes are held without the helper. No new sound/capture.

The user reports two reboots. The preceding recorded boot also ran 7.3.0-rc2,
with no retained panic or trial-return invocation; its reset cause remains
unknown. Promotion is verified, but this does not establish B01 reliability.
