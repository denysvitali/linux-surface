boxes closed: 3 of 47; newly closed: none.

# WX: restore GNOME after console-only audio verification

Boot `11455cda-536d-4af7-bffe-7a17ce29650c`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Cause:** the audio trial explicitly set `systemd.unit=multi-user.target`.
The normal default was already graphical and GDM was enabled, but neither
GDM nor graphical.target had started. The diagnostic console was left active
after the speaker test.

**Changed:** started `graphical.target` on the running boot. Removed the
console target override from the saved WX GRUB entry and its entry copy.
Trial preparation now drops inherited target overrides unless the caller
explicitly selects one. Documented restoring the desktop after console work.

**Observed:** GDM and GNOME Shell started. User `dvitali` has an active
Wayland session on VT2; VT2 is also the foreground console. Mutter reports
display power mode 0 (on). No reboot or display-module operation was needed.
No additional audio playback or microphone capture was performed.

**Meaning/next:** desktop startup is restored. Stop this repair; full D01
acceptance and the cause of older interrupted boots remain outside its scope.
