# 09 — Guarded test harness audit (read-only, 2026-08-21)

Scope: read-only audit of the guarded speaker test harness on hardware. Nothing
was modified, no GRUB entry armed, no reboot performed. All commands were reads
(`/proc`, `/sys/module/*/parameters`, `/boot`, `/var/lib/spx-speaker-autotest`,
repo scripts) except one harmless extraction of the initramfs into `/tmp` for
content listing.

## 1. Harness scripts (what runs on a guarded boot)

Chain: systemd `spx-speaker-autotest.service` -> `/usr/local/sbin/spx-speaker-autotest`
(root wrapper, mtime 2026-08-09) -> `scripts/spx-speakers-up.sh` run as user
`dvitali` via `runuser`.

- `/etc/systemd/system/spx-speaker-autotest.service`: oneshot,
  `ConditionPathExists=/var/lib/spx-speaker-autotest/armed`,
  `ConditionKernelCommandLine=snd_soc_wcd934x.spx_persist_stream=1`,
  `ConditionKernelCommandLine=panic=10`. Unit is **enabled but inactive**.
- Root wrapper: refuses without `armed`; consumes the marker (`mv` to
  `consumed-...`) **before any hardware access**, so a service retry or later
  boot can never replay a first-stream experiment. Re-checks three cmdline
  invariants itself and writes `cmdline-rejected` if they fail. Grants ACLs on
  `/dev/snd/*`, captures before/after dmesg + journal + pstore + ALSA ACLs per
  run under `/var/lib/spx-speaker-autotest/runs/<boot_id>-<attempt_id>/`.
- Only `SPX_[A-Z0-9_]+=<value>` lines from `/var/lib/spx-speaker-autotest/test-env`
  are injected as env — good injection hygiene.
- `scripts/spx-speakers-up.sh` (760 lines): step [0] verifies ~30 boot
  invariants (cmdline args, module params via `require_param` with 0/1<->N/Y
  normalization, watchdog ownership by PID 1, setsid present), then bring-up,
  presence sampling until a real `MCP_SLV_STATUS=0x1` is seen (later zeros are
  tolerated as the documented stale latch), cold-init replay, DAC-only mixer
  path, tone with explicit 12000/48000 geometry, serialized master DP snapshot
  gate, PA teardown, GPIO-low parking verification, fault grep over logs.
- Current `test-env`: `SPX_AMP_GPIO_ON=0x04 SPX_EXPECT_FORCE_TIMER_PACING=0
  SPX_TONE_FORMAT=S16_LE SPX_EXPECT_SPK_PATH=right SPX_EXPECT_GPIO_PIN=2 ...
  SPX_EXPECT_WIN_PA_PROFILE=0 SPX_READBACK_ONLY=0` — i.e. the v19/v28 endpoint-B
  pin2 baseline.

## 2. Autotest unit location

Not in the repo. Lives at:
- `/etc/systemd/system/spx-speaker-autotest.service`
- `/usr/local/sbin/spx-speaker-autotest` (bash, root-owned)

Both are outside git, so they are not covered by repo review or version control;
the only change record is mtime. This is a gap: the harness that gates hardware
tests is untracked and could drift silently from what CLAUDE.md documents.

## 3. GRUB state

- `grub-editenv`: `saved_entry=spx-audio-rescue`, `next_entry=` (empty). Safe.
- No `armed` marker exists; last autotest run was today's
  `c962c2a7-...-20260821T140803Z-981` which completed status 0 (guarded v28-style
  run: device-0 observed after 1 sample, DP4 banks both `0x01000607`,
  parking verified).
- Custom entries in `/boot/grub/grub.cfg`: `spx-known-good`, `spx-rescue`,
  `spx-camera-multi-v23`, `spx-audio-rescue` (default, blacklists
  soundwire_qcom/wsa881x, fallback initramfs), `spx-speaker-v28-music`,
  `spx-speaker-v29-acdb-cal`, `spx-speaker-v30-cal-bisect`.
- **Gap A:** v28/v29/v30 all use DTB `.speaker-right-v19` (sha256
  `3c32f9a3...`, matches the documented value) and differ from each other only
  in `q6afe.spx_auto_speaker_cal` (v29 has it, v30 does not but its title claims
  "live debugfs cal firing" — no debugfs knob appears in its cmdline; title vs
  content mismatch worth confirming intent).
- **Gap B:** none of the audio entries pins the initramfs to a dated copy; all
  use the shared `/initramfs-linux-surface.img` (see finding below).

## 4. Module / DTB / initramfs inventory (kernel 6.18.3-1-surface+)

Installed `updates/` newest copies:
- `q6asm-dai.ko`, `q6asm.ko` — 2026-08-20 17:35 (spx-keep-asm era)
- `soundwire-qcom.ko` — 2026-08-11 22:29
- `snd-soc-wsa881x.ko` — 2026-08-11 21:31
- `snd-soc-wcd934x.ko` — 2026-08-09 14:29
- `modules.dep` regenerated 2026-08-20 17:35; `modinfo -n` resolves all three
  key modules to their `updates/` paths.

**Initramfs-vs-modules check (the stale-copy hazard from CLAUDE.md).**
`/boot/initramfs-linux-surface.img` is mtime 2026-08-11 22:30 — *older* than the
2026-08-20 `q6asm-dai.ko`/`q6asm.ko`. I extracted the image read-only to
/tmp and listed it: it bundles exactly five audio .ko files
(`soundwire-qcom.ko`, `snd-soc-wsa881x.ko`, `snd-soc-wcd934x.ko`, `wcd934x.ko`
in `usr/lib/modules/.../updates/`, plus `wcd934x-wdsp.ko`). SHA-256 comparison
of those four against `/lib/modules/$(uname -r)/updates/` shows **all MATCH**.

Interpretation: the four control-path modules in the initramfs are current, so
the classic "stale bundled copy" trap does not apply today. However:

- **Gap C (OPEN, needs one decision):** the 2026-08-20 `q6asm-dai.ko` and
  `q6asm.ko` are NOT in the initramfs at all (they never were — mkinitcpio
  bundles only the modules listed for early load, and q6asm loads later from
  the real root). That is correct behavior, but it means any future change to
  `soundwire_qcom`/`wsa881x`/`wcd934x` still requires `sudo mkinitcpio -P`;
  nothing in the tree or docs enforces that pairing mechanically. The mtime
  heuristic alone (initramfs 08-11 vs modules 08-20) looks alarming but is
  benign because the differing modules are not bundled ones. Recommend a
  post-install hook or a check in the harness that hashes bundled modules
  against disk at step [0].
- **Gap D:** `vmlinuz-...-slimfix` is from 2026-06-29 while all modules are
  newer; vermagic has been stable so far (today's run loaded everything), but
  there is no recorded sha256 of the kernel image anywhere in docs, so kernel
  drift would be invisible to audits like this one.

## 5. Test-readiness analysis

Ready-to-run state right now: yes, for an automatic guarded first-stream test.
Evidence: unit enabled, conditions match the audio cmdline, marker consumed,
no stale `armed`, default entry safe, today's run passed every gate including
GPIO-low parking, and PipeWire was left stopped as designed pending listening
confirmation. The next guarded boot needs only: rebuild/restage if anything
changes, write `test-env`, arm the fresh entry last.

Blocking caveats before the next listen:
1. First-stream rule: the boot's first stream is the only valid measurement —
   already enforced by the consumed-marker design. Good.
2. The harness requires `MCP_SLV_STATUS=0x1` in the GPIO-high window; today's
   log shows it appeared after 1 sample. Fine.
3. `spx_wcd_gpio.ko` insmod returns EAGAIN by design and the script greps the
   kmsg block instead of the exit code. Today's log shows the expected
   `SPX GPIO managed:` line, so this works, but note the helper must stay
   EAGAIN-by-design or the grep target changes.

## 6. Hardcoded assumptions flagged

- `REPO=/home/dvitali/Documents/git/linux-surface-kernel` and user
  `dvitali` are hardcoded in the root wrapper (fine for this machine, breaks
  portability silently).
- Step-[0] invariant defaults: `SPX_EXPECT_SPK_PATH=left`,
  `SPX_EXPECT_GPIO_PIN=$SPX_NATIVE_GPIO_PIN` (=2 for left path),
  `SPX_EXPECT_FORCE_TIMER_PACING=1`, win knobs expected 1. Every deviation must
  be declared through `test-env`; forgetting one aborts safely rather than
  mis-testing (verified: the v17-era boolean N/Y mismatch aborted pre-hardware).
- The harness assumes the ADSP remoteproc is found by name (`name == adsp`) —
  fixed after the old hardcoded `remoteproc1` bug; OK now.
- The harness assumes `speaker-test -s 2` prints `- Front Right` without the
  numeric prefix (string check corrected earlier); any speaker-test upgrade
  could silently break that gate.
- Cross-GPIO tests require explicit `SPX_ALLOW_CROSS_GPIO=1` AND
  path==right AND pin==1 — the v21 guard is intact.
- `spx-speakers-up.sh` still hard-requires
  `slim_qcom_ngd_ctrl.spx_pio_mode=1`, `spx_allow_full=1`, `spx_pin_after_qmi=1`
  on the cmdline; entries missing them fail fast at step [0].

## Bottom line

The guarded chain is internally consistent, currently disarmed, and matches the
documented v28 endpoint-B baseline. The two structural gaps are: (C) no
mechanical enforcement that bundled initramfs modules equal installed ones
(manually verified matching today), and the untracked location of the autotest
wrapper/unit outside git. Everything else found is documentation-level drift
(v30 entry title vs cmdline) rather than a safety problem.
