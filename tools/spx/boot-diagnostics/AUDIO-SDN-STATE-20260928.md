# SD_N / WCD GPIO live state: candidate 1 refuted (2026-09-28)

## Measurement

Read-only, on the live Y boot `b5f0a540-3e81-4415-b08c-f869e01349a2`, no
playback and no writes. The WCD9340 register window is exposed at
`/sys/kernel/debug/regmap/217:250:1:0` (`name` = `wcd934x-slim`), which is the
same regmap the driver's `spx_wsa_powerdown_set()` writes.

    0x40 00   0x41 00   0x42 00   0x43 18   0x44 00 ... 0x50 00

* **0x42 (GPIO direction) = 0x00** -- every pin is an input.
* **0x43 (GPIO value) = 0x18** -- pins 3 and 4 high; **pins 1 and 2 low**.

Polarity was measured 2026-07-29 (`wsa881x.c` comment): physical **HIGH = amp
ON**. So on the left amp, SD_N (wcd-gpio pin 1) is physically **LOW = amp OFF**
right now, and it is not the driver holding it there.

## Why the driver is not holding it

Live `/sys/module/snd_soc_wsa881x/parameters`:

    spx_enumerated_mode        = Y
    spx_write_only             = N
    spx_blind_rmw              = N
    spx_powerdown_gpio         = 1
    spx_swap_dac_master_ports  = N
    spx_stream_port_mask       = 1

Both SD_N drive sites are gated on `spx_write_only`, which is `N`:
`wsa881x_runtime_resume()` does `spx_wsa_powerdown_set(wsa881x, 0)` only inside
`if (wsa881x->spx_write_only)`, and `runtime_suspend()` likewise at `1`. So in
enumerated mode **nothing in the driver ever drives the WCD SD_N line**; it sits
at whatever the codec reset/power-on default left, which is 0x00 direction with
pin 1 low = amp off.

This also corrects a reading of the Y record. The record's "no new FIFO or PA
errors" is *not* evidence that the amp was never driven: dmesg shows real DAPM
power-up on the left codec at both playbacks, e.g.

    652.450  device=1 DAC slave port 1 -> master DP1 (swap=0)  active_ports=1
    652.758  PA DAPM event 0x1 / 0x2      654.229  PA DAPM event 0x8
    652.745  RDAC DAPM event 0x1          654.277  RDAC DAPM event 0x8

`PA DAPM event 0x1` is the power-up, and the write-only SoundWire path was used
successfully -- it is the *physical* SD_N pad that was never driven, which no
software register event can fix. That reconciles "the driver ran cleanly" with
"the pad is off".

The `SPX: SD_N on wcd-gpio pin N` dev_info line is **absent** from dmesg, but
the pin is confirmed independently from the device tree
(`sc8180x-wcd9340.dtsi`), so nothing here rests on inference:

    left_spkr  reg = <0 3>  powerdown-gpios = <&wcdgpio 1 GPIO_ACTIVE_LOW>
    right_spkr reg = <0 4>  powerdown-gpios = <&wcdgpio 2 GPIO_ACTIVE_LOW>

**0x43 = 0x18 = BIT(3) | BIT(4)** -- and those are the only bits set. So neither
amp's SD_N is high: pin 1 (left, the one that enumerated and is playing) and
pin 2 (right, the one that never enumerates) are both physically LOW = both
amps off. That single fact explains both halves of the long-standing problem:

* the left amp gets no acoustic output even though its full PA/RDAC SoundWire
  write sequence completes without error, because the pad feeding the amp is
  never driven high;
* the right amp never enumerates, which its own DT comment independently
  attributes to SD_N state ("holding one amp in shutdown makes the other one
  appear").

It also means the two symptoms share one cause, so candidate 1 is a candidate
for both. The earlier `spx_pin2` "hardware failure" conclusion is not
consistent with a pin the DT and the driver both treat as ordinary, and the
`0x43` read shows the pin is not being held in a broken state.

## Consequence for the trial plan

`AUDIO-AFTER-Y-20260927.md` proposed candidate 1 = "drive pin 1 DIR and set it
high" because the older working state had `0x42=0x1e` / `0x43=0x1e`. The
direction half of that is right and remains untried, but the value half is
already true for pins 3/4 and false for pin 1, so the *delta* that matters is
precisely **pin 1: direction input -> output, value low -> high**. That is a
single-bit change in each of two registers and it is still the smallest
untried variable. It is NOT refuted -- what is refuted is the idea that GPIO
state is merely "unconfigured", since we can now see it is explicitly
input/low with pins 3-4 high.

**Candidate 2 is cheaper and needs no rebuild:** `spx_swap_dac_master_ports` is
a live module parameter (currently `N`), and the dmesg line
`device=1 DAC slave port 1 -> master DP1 (swap=0)` shows the single active
stream is on master DP1. Flipping it to `Y` routes that same single stream to
master DP4, which is the other port the older working state used
("master DP1/DP4 bank 0").

## Ordering, and the one gate

One variable per trial; do not change both. Recommended order is candidate 2
first: it is a **runtime parameter, not a rebuild**, so it costs no boot
rehearsal and no new kernel, and it is reversible in seconds. Candidate 1
needs a one-shot GRUB entry because the SD_N line must be driven before the
codec is powered, and the driver has no path that does that in enumerated mode.

Either way the judge is the internal mic (`spx-mic-judge.py`) with a >8 kHz
tone on a speaker-side DMIC, comparing high-band energy against the archived
-93.2 dBFS DMIC0 floor. **Any playback must be explicitly requested by the
user for that specific run** -- see memory `spx-no-unrequested-sound.md`; the
user was blasted at night by an unrequested run, and this session deliberately
made no playback.

## State

Nothing was written, no module parameter was changed, nothing was deployed, no
GRUB entry was armed, and no reboot was performed. Y remains live with
`spx-known-good` as the default.
