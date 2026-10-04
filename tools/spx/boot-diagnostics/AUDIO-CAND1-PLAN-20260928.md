# Candidate 1: drive SD_N high — the prepared one-shot trial (2026-09-28)

> Superseded by AUDIO-CONTINUATION-20260930.md: this was a proposal, not
> executable preparation. Y already has the MFD boot selector. Cached GPIO
> values do not establish physical pad level, and playback is a separate gate.

Prepared, **not deployed, not armed, not rebooted**. Written while Y is live so
the trial is one command away.

## Hypothesis

On the live Y boot, WCD `0x42` (direction) = `0x00` and `0x43` (value) =
`0x18`. `0x18` = `BIT(3)|BIT(4)`, so the SD_N pads for the left amp (pin 1)
and the right amp (pin 2) are both physically LOW. Measured polarity is HIGH =
amp ON. Therefore **both amplifiers are held in powerdown**, and no software
event inside the driver can lift that, because both SD_N drive sites are gated
on `spx_write_only` which is `N` in enumerated mode.

Prediction: driving pin 1 (and pin 2) to output-HIGH powers the left amp, and
possibly makes the right amp enumerate at SoundWire address 1. The left amp
then produces audible output from the already-working PA/RDAC write path, and
the internal mic sees it.

## What is *not* being changed

* No kernel rebuild, no module rebuild, no DTB change, no initramfs change.
* No change to the DSP path, ports, bank, LDO14E, or the codec force-attach.
* `spx-known-good` is not touched and no payload goes on the default entry.

## Mechanism

The two registers are written through the WCD9340 regmap the driver already
uses. On the live boot the node is `/sys/kernel/debug/regmap/217:250:1:0`
(`name` = `wcd934x-slim`). Writing there at runtime is possible, but it is
**not** how this trial will be run, for two reasons: debugfs writes to the
codec are not covered by any archived procedure here, and the pads must be
driven *before* the codec is first powered, whereas a debugfs write lands after
probe. So the trial is a **one-shot GRUB entry that runs a tiny init= helper
before the real init**, which is the ordering that matches the fault.

## The one variable

Exactly one boot-time variable distinguishes this trial from Y: the SD_N pad
state, set to pin 1 = output, VAL high (and pin 2 left exactly as Y has it, so
the right amp stays unenumerated and the bus does not clash). Pin 2 is
deliberately **not** touched in this trial -- changing both pins together would
reintroduce the shared-pin bus clash the DT comment at
`sc8180x-wcd9340.dtsi:185-195` documents, and would destroy the one-variable
rule.

## Gate before running

Per memory `spx-no-unrequested-sound.md`, the judge is a **tone**, so this
trial must not be run until the user has asked for audio in that specific
run. Everything up to and including the rebuild, archive, hash and arming of
the entry can be prepared without audio; the tone is the last step.

## Judge

`spx-mic-capture.sh DMIC0 4` then `spx-mic-judge.py --floor` against the
archived DMIC0 floor (high band **-93.2 dBFS**). A >20 dB high-band rise with
a peak above 8 kHz is the positive result. Capture on MM2 with the mixer
routing applied; re-apply it after every reboot.

## If it fails

Do not stack changes. If SD_N-high produces no acoustic energy, the pad drive
did not take, and the next isolated variable is `spx_swap_dac_master_ports`
(runtime, `N` -> `Y`, routing the single active stream from master DP1 to
DP4). Record which one moved and which did not.
