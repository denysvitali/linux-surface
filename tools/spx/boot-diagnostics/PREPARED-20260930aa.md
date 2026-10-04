# AA: silent SoundWire enumerator identity diagnostic

AA is installed and independently reviewed from known-good boot
`e0479717-1fe0-4a8f-a6ac-af198c4b703a`, `6.18.3-1-surface+`.
The authoritative selection state is `/var/lib/spx-boot-diagnostics/attempt.json`.
Read that state and actual boot identity before acting; this record does not
establish a successful AA boot. Do not reselect a consumed trial.

The distinct release is `7.3.0-rc2-spx-mainline-20260930aa+`.
Relative to Z, source adds only the bounded, default-off existing-read logger
in `drivers/soundwire/qcom.c`; configuration changes only LOCALVERSION.
The DTB remains exact Z. Cmdline changes the attempt marker and adds
`soundwire_qcom.spx_enum_diag=1`, preserving pin1, force attach, transport and
DAC selectors. No playback, capture, PCM probe or live device rebind is scheduled.

Build, source/config and private initramfs are archived under
`/var/lib/spx-boot-diagnostics/attempts/20260930aa/build`. Native Image, DTB,
modules, strict depmod, vermagic, embedded config and private logger verification
passed. Independent installation review rehashed 1,025 build files, 272
symlinks, 202 installed module-tree files, 15 payload/recovery/runtime files,
a 150-file preboot snapshot and 10 deployment scripts. GRUB syntax and systemd
unit verification passed. Recovery artifacts are unchanged and hash-verified.
The consumed Y/Z boot slot was copied/rehashed before retirement to make room;
its permanent archive is `AA/retired-boot-slots/20260927y`.

| Evidence | SHA256 |
| --- | --- |
| Build manifest | `92f2219ca1f4ed0d7db3816b132410200019e12778e633b26368014f569cf5f1` |
| Installed module manifest | `bca9b1a862d11afaceabe400d91c4d2f20ed4c38aabb798970eb88d6cc0b5a8a` |
| Installation review | `d35438e89b15f5259828b202d979ef9abce08206be3de55e0fdcac7b8d46722e` |
| vmlinuz | `91d02c0257f99ae024b5172b885778a8e46ad4fa7c3641f5867c2bd7b41ee15f` |
| initramfs | `845b79dd7edd02c8eb4bdf8bc630bb8e77525569c98231cfd30a00b8469e73a0` |
| DTB, exact Z | `ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a` |
| Retired Y/Z slot manifest | `dedbad5738dc44e80d948daeb43a623cf431330fcae890a966dcee6c4f65c702` |
| Native continuation review | `430f7aa3af3d8ca49d0b39a20649768f67be7b845d4795453698c0c3086679db` |

The AA collector at 620 seconds archives/hashes before deciding whether to
stop the 900-second fallback. Diagnostic success requires 1..8 raw transactions,
at least one successful pair and its decoded identity, the Z GPIO software
state, controller/DSP startup and graphics/Wi-Fi/touch/soundcard baseline,
no selected kernel faults or WSA FIFO/init/status errors. Both declared 2010
nodes must retain codec drivers. The observed firmware-less 2110/unique3 node
may remain UNATTACHED/N/A and unbound; other extra identities fail this scope.
This is a diagnostic criterion chosen before selection. Z's original expected
2-device topology failure remains unchanged. AA success does not prove physical
attachment, correct enumerator contents or acoustic output. Register values may
be cached and forced logical status differs from the raw hardware snapshot.

Native continuation is enabled for the current Codex thread, prompt `continue`;
retired resume marker absent. The one-shot queue retains a request marker and
schedules a 30-second guard. Immediately before reboot that guard rechecks
current boot ID, pending entry, known-good default, absent EFI BootNext, module,
payload/recovery/runtime hashes and enabled timers. Any guard failure clears
only its own selection on the same boot. Userspace fallback does not validate
recovery across EFI handoff; repeated experiments are explicitly authorized.

On continuation inspect actual kernel/boot ID/uptime and AA timers first. If AA
is running, collect the enumeration trace and wait for the automatic finalizer;
run `review-aa-result.py` only after final-result and finalizer-action exist.
Preserve raw words, read return codes, decoded fields, raw status versus forced
status, and firmware-node/driver binding evidence before proposing a next trial.
If known-good has returned, archive AA's prior-boot logs and fallback evidence.
