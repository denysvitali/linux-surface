# Working SPX boot preserved; other installed combinations pruned, 2026-10-02

User instruction: "Continue. Keep the working boot combination intact and prune
the rest." This authorizes retiring previously protected experimental slots and
obsolete installed modules. Original logs/source/build archives remain preserved.

Current boot5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5 /6.18.3-1-surface+ is unchanged.
The exact spx-known-good menu entry and cmdline are preserved, including pin2,
core enumeration/force attachment and all recovery settings. Default remains
spx-known-good; next_entry empty; no BootNext. GRUB environment and EFI loader
bytes unchanged. No reboot, trial selection, live reset/rebind or PCM/input test.

Retained payloads, byte-exact before/after:
- /boot/vmlinuz-6.18.3-1-surface+-slimfix
  c202330dbc6b4145b0629a057109745dc803621b94807ec2965ad705818049d9
- /boot/initramfs-linux-surface.img
  c3f4c3cd843f45ded2ae79ac12114a5c5988edb2cb6ac9c32a352f2afff4a5a8
- /boot/dtb/qcom/sc8180x-surface-pro-x.dtb.wsa
  1ef46c32dde48d197f5683687c88ec3f2d2ecf33f20319b09d45127d49f16a3e

The entire known-good module tree remains byte-exact,5183 files/links. Kernel
package remains installed; its working modules and all live firmware/userspace
services are retained. Other30 module-version directories have been archived and
removed, including obsolete bisects and installed mainline trial versions.

All obsolete kernel/initramfs/DTB copies,7 residual trial directories, experimental
menu entries/backups and old boot-partition log copies were retired.55 obsolete
GRUB scripts/backups and88 old per-attempt service/timer units (44 timers) removed;
those units were inactive/failed and specifically gated by old spx_attempt values.
Shared diagnostic tools and generic conditional services are retained for future
work. Existing evidence under /var/lib and offline build/source trees is retained.
370 explicit removal paths, never a blanket removal of /boot or module roots.

Active menu contains only known-good and UEFI firmware settings. 09_spxtree now
preloads the retained .wsa tree, replacing its reference to the retired generic
DTB. The working entry itself still loads the original .wsa file byte-for-byte.
40_custom emits only the exact working entry. Disabled generic packaged menu
scripts remain disabled. The initramfs preset's ALL_kver points to the retained
slimfix kernel, with only the default image selected; no image was rebuilt.

Before any removal, full copies of /boot, /etc/grub.d, /etc/default/grub,
/etc/mkinitcpio.d, /etc/systemd/system and /usr/lib/modules were privately archived
and rehashed. Source and archive were checked again before mutation. Snapshot
2504957644 bytes, stored under:
/var/lib/spx-boot-diagnostics/boot-prune-20261002/snapshot
Manifest e987abdeb4133a26cf1241bfbd8c29204f531310731ee51fa7d2fb69ba7604cf.
Original absolute paths map beneath snapshot (e.g. snapshot/boot/... and
snapshot/usr/lib/modules/...). Symlinks preserved without following build links.
plan.json/removed-paths.json/result.json and command logs describe each operation.
Restore individual reviewed paths from this snapshot; do not blindly restore an
old experimental menu or arm a retired failed attempt. First preparation's sh -n
check was incorrectly applied to40_custom's GRUB-language tail; no live mutation
occurred. Its failed script is retained in the sibling preparation-first-failure
record; corrected checks validate emitted GRUB text with grub-script-check.

/boot available increased from3096576 to436535296 bytes (~416.31MiB, df417M),
reclaiming433438720 bytes (~413.36MiB). Remaining boot files, except the regenerated
menu, are byte-exact original survivors. Active and regenerated menus pass GRUB
syntax checks and resolve only retained payloads; known-good module/EFI integrity
and pending-selection checks pass. No reboot was needed to verify file integrity.

AM7.3.0-rc2-spx-mainline-20261001am+ remains offline, fully built/archived. No AM
payload/module was installed or selected. See BUILD-20261001am.md for exact source
and candidate checks. Historical AL/AK attempt hash maps now refer to retired
installed files; use the private snapshot/original attempt build archives to verify
those historical artifacts. Future deployment tooling must use fresh working-boot
recovery/runtime checks and stage new trial units instead of requiring obsolete
live files. All original attempt metadata/results remain intact. Touch repair,
outgoing callback execution/late-log retention and EFI early recovery remain
unvalidated; do not infer hardware success from cleanup.
