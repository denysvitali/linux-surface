# AJ: detached PA gain guard, silent pin2 trial

AJ is a distinct `7.3.0-rc2-spx-mainline-20260930aj+` kernel/module/private
initramfs build, prepared from verified known-good boot
`81412181-f873-4ba8-a5fe-07f5376bf680` after AI's automatic fallback. Selection
state is authoritative only in the private attempt.json; this document is not
a queue or hardware result. All three boot payloads have AJ-specific paths.

Only functional source delta vs AI: put_pa_gain calls the existing availability
helper and returns-ENODEV before PM/IO/delay for a detached enumerated-mode slave.
Native object compiled without warnings;624 exact-C callback differential cases
passed ASAN/UBSAN. Attached/nonenumerated gain ramps/error behavior unchanged;
an entry-time status check cannot serialize an asynchronous subsequent detach.
Config only LOCALVERSION AI->AJ. No touch, GPIO, routing, retry or delay change.

Build1209files/272symlinks, module tree202files/187KO/vermagic records. Full source
and config are build/source.diff and build/artifacts/.config; the copied15-file
dtb-build tree retains historical AG source/config, with no additional DT delta.

| Artifact | SHA256 |
| --- | --- |
| Kernel | `4c082cab2b2a029ee896d104973d3784d3bc018c0ca4f533fd07764c25cd27d0` |
| Initramfs | `3840974352ddd84e926a51439c33b37e5f772ed6ecfe372a7d06fc50ef978a63` |
| Corrected DTB, exact AG/AI | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |
| Config | `22f5af56d67ed30c8da82b58223dc355164c3ff60f3a09667af7d38189ad6b24` |
| Full source diff | `16938e064ea05427013d32a41bb1aa790ebbf31900f96e831d912942d0a666b0` |
| Build manifest | `e7e839d812607b2e943155c49c059a5e5c39a59675d7dd0a02d361937184ff5f` |
| Modules manifest | `153048d0737d61e40e06ba800bc7f6c5e35e6b233beecede7ad0d95dcd41255f` |

Command line differs from AI only in the attempt marker. Pin2/raw overrides-1,
right2110/unique4 matches DT, left2110/unique3 remains declared. Native force/
core/watchdog0/exactwindowsN; command diagnosticY16history/max2dumps/34lines,
enumY max8 transactions, touchY8windows/48records/384 lifetime. These are software
diagnostics, not hardware acknowledgment or physical GPIO/routing proof.

The AJ collector and independent judge reproduce AI's criteria after identity
substitution. Strictly require right Attached/device1/init entry, exactly two
DT-backed2110 nodes, GPIO4/1c, native0/no selected command/FIFO/bus/clock errors,
DSP/card/graphics/Wi-Fi/touch ready/taint0 baseline and bounded diagnostics. A
separate pin2 diagnostic does not control fallback. A clean startup is reported
separately and never replaces final touch readiness. Collector620s/fallback900s.

AI final393 manifest9985c314... failed nativepath plus touch readiness;
actual900s fallback returned to current known-good,559return33e7468b... archived.
Original AI source/config/results frozen before guard in16postf79d9164...;
12guardcandidate2a5fa5be... preserves exact tests/source/logs. AI not re-armed.
One inactive42,469,888-byte historical backup was preserved/rehashed before
removal for boot space: vmlinuz-linux-surface.20260611-151023, SHA5ccc9915...;
private retirement archive retains configs/helper/restore instructions. Active
AI/AE/AG and recovery payloads verified unchanged.

Before queue: independent installation/prequeue/source/module/GRUB/systemd scope
and runtime hashes must pass, continuation thread/prompt/live host must be freshly
verified, and all records archived. Keep known-good persistent default; select
AJ once, recheck bootID/pending choice and hashes immediately before reboot.
Collect actual AJ before choosing another experiment. No manual audio/PCM/capture/
input-event reads or live component restart/reset/rebind. EFI/early-kernel
recovery remains unvalidated; user authorized the experimental reboot loop.
