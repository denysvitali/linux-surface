# AN exact-AM handoff, prepared 2026-10-02

AN may depart only from passing AM boot
`6dfad462-25b7-4e5e-90fc-3bd18c1c3095`. The actual AM baseline passed at620.68s,
independently verified245result files; manifest05523dfc62a3bbc99d60aa7ddb9b10bbff84f9f184399a26d7915a902794de73.
AM post-result21files manifestb72f5333bc88d855c7ce181f78cf6db37e2bf61fdda7a14e5aaacb20e8cb1c84.

AN attempt20261002an reuses release7.3.0-rc2-spx-mainline-20261001am+ and installed
`/boot/spx-trial-20261001am/{vmlinuz,initramfs.img,spx.dtb}`. No new slot/modules,
no retired trials restored. Kernel d90c8467..., initramfs3fa86a1c..., DTB5adbda17...
unchanged. Archived1354buildfiles/272links and202modulefiles exact AM; source
diff2b04f216..., configf0c4a7ff... unchanged. Only kernel cmdline attempt marker
changes AM->AN, while menu ID/diagnostic identity changes to AN. Pin2/nativeforce0,
bounded command/enumeration/startup selectors and strict620/900 policy unchanged.

Independent install review rehashed archive and live modules,17payload/recovery/
runtime files, full5183working module files/links, original3recovery payloads,
known-good entry and EFI loaders. All12strict result expressions unchanged;
6strict scope rejection cases,2positive/11negative extracted actual preboot cases,
1positive/8negative extracted fallback cases pass. systemd unit validation and
GRUB syntax checks pass. AMfallback stopped after verifiedpass; AN timers enabled
and inactive under current AM marker. Generic600s return additionally excludes AN.

Outgoing223file snapshot manifest6d19b49f814d07ef187286ff6e348f2db2f664bc2a40fe516489515cc3ab2c48
retains actual AM boot ID/cmdline/raw kernel chronology and pstore baseline before
shutdown. Ten deployment sources manifest767e648430064a9f7decff78e755346daa7c4b985dc962a2cd929665bb76a253.
Native Happy same thread, host2794, daemon continuation true/promptcontinue;
actual retired marker `~/.local/state/spx-port/resume-armed.json` absent.
First inherited preparation metadata draft retained and parentpost provenance
corrected before installation; source/artifact hashes never changed.

Select once with exclusive request marker and30s scheduled immediate guard.
Guard requires original actual AM result/review/source/payloads and frozen parent
archives, live readiness/connected Wi-Fi/taint0, full protected recovery, exact
pending AN/defaultknownGood/noBootNext, actual unchanged AM boot ID. After sync,
fresh ID/pending check and an explicit kernel-log outgoing identity marker precede
reboot. Actual queue-review.json/reboot-check-passed.json are authoritative; this
preparation record does not claim a hardware boot or callback execution.

On native continuation, read current boot ID/cmdline first. For actual AN run
`sudo -n python3 tools/spx/boot-diagnostics/review-an-handoff.py` early. It freezes
consumed one-time proof and pstore, comparing against outgoing baseline. Callback
completion requires new/changed retained console with the exact AM identity
marker followed in the same file by SPI-HID begin and complete. Without that chain,
execution/persistence remains unverified. Journal absence is not callback absence.
Software completion does not prove physical rail-off or reliability.

Collect actual AN620s final-result, then run review-an-result.py and freeze source/
logs before another choice. Failure leaves900s checked fallback armed; confirm
actual knownGoodreturn and preserve outgoing logs. Never blindly re-arm a failed
image. Persistentdefaultspx-known-good, unchanged workingkernelc202330d.../
initramfsc3f4c3cd.../DTB.wsa1ef46c32.... EFI/early-kernel automatic recovery remains
unvalidated. No manual audio/PCM/capture/input or live reset/rebind.
