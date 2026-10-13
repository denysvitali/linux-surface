boxes closed: 3 of 47; newly closed: none.

# Audio EIO investigation — diagnostic WIP, no hardware fix

Automatic coverage unchanged: **11/40 functional**, **36/52 inventory**,
**44 blocked, 1 failed, 0 errors**. Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`,
kernel `7.3.0-rc2-spx-mainline-20261004bg+`. This is offline work, not a new boot.
[Generated checklist](../../../AUTO-HW-CHECKLIST.md); detailed private evidence:
`/var/lib/spx-boot-diagnostics/boots/93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d/hw-validation/report.json`.

## What changed

Failure-only logging in existing `spx_audio_state_get` reports its failing stage,
target register and existing return, or actual/expected canary when the read
succeeded. All fatal checks, return values, register operations, locks and settle
delays remain unchanged. No extra reads, retries or hardware constants/settings.
The diagnostic is **not installed, linked as a module or loaded**. Installed Python
origin/errno logging and the separate monitor cleanup fix remain as before.

## What the six offline avenues established

- Source/stored ownership holds SoundWire power on through serving. NGD suspend
  attempts just before failure explicitly skipped power-off. Assumption: no
  external policy change; there is no original failure-time PM snapshot.
- Ordinary bridge transactions and shared paged-regmap access have the required
  locks. The old edge-poll/page-selector defects are already corrected. Legacy
  direct helpers can bypass transaction ownership, but none is implicated here.
- FIFO/port/overflow logs begin **after close starts**, not proof of primary cause.
  The saved `OSError EIO` has no traceback; the callback remains only a source match.
- No integer boundary matches failure. A separate source-proved u32 byte-counter
  wrap shifts PCM ring phase at about6h13m; it does not explain EIO at12h19m and
  remains unpatched. The 6.18 relay has no equivalent periodic state checker.
- The unchanged bursty fixture passed one focused run (7.541s). Its fake sink can
  count underruns after descheduling; exact waveform bytes do not prove timing.
  Prior full118/119 failures are unresolved; no oracle/buffering change.

## Offline validation and next step

73 stubbed executions of the actual old/new callback preserve return values,
output, access count/order and lock cleanup, including every injected failing
operation and both bad canaries. Strict checkpatch:0 errors/warnings/checks.
Candidate object compiled with the saved GCC kernel flags/config and canonical
headers:exit0, no diagnostics. Normal O= build was blocked by in-tree build files;
canonical metadata was restored, with no tree clean or live install. These are
source/stub checks, **not hardware validation or proof of EIO origin**. Bridge return2
still cannot identify which underlying SLIMbus transport operation failed.

Stop: primary cause is unproved and no supported safe correction remains.
A separately authorized playback run or normal boot can supply the installed
Python traceback. If it identifies this callback, the prepared native diagnostic
needs deliberate deployment before using its failing-stage evidence. No playback,
capture, amp/PM change, DSP reattachment, module reload or reboot in this round.
Offline briefs/test artifacts: `/var/tmp/spx-audio-eio-depth-20261013`.
