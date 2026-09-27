# Internal microphone restored as an objective acoustic oracle (2026-09-28)

## Correction to the Y record

`AUDIO-AFTER-Y-20260927.md` and `RESULT-20260927y.md` both record that the
built-in capture path is not usable as an acoustic reference, and that
"No USB microphone is currently enumerated" therefore leaves no objective
oracle. **The capture path was never broken. The probe was incomplete.**

Y's `y-internal-capture-probe.py` opened `hw:0,0` (MultiMedia1) with
`S16_LE / 48000 / 2ch` and applied **no ALSA mixer routing**. On a DPCM card
the frontend needs an explicit DAPM path to a backend DAI, which here is
created by ALSA mixer controls, not by device tree.
`dpcm_fe_dai_open()` in `sound/soc/soc-pcm.c` walks that path and, when
`be_clients` is empty, returns `-EINVAL` after logging

    ASoC: no backend DAIs enabled for MultiMedia1, possibly missing
    ALSA mixer-based routing or UCM profile

That is the `-EINVAL` arecord reported. Two earlier red herrings are also
withdrawn: `MultiMedia1 - Capture: State: new / No active DSP links` only
means the *runtime* `be_clients` list was empty, and the absence of a
`SLIM Capture` directory under `/sys/kernel/debug/asoc/` is expected for a
`no_pcm` backend link.

## What actually works

`linux-surface-kernel/scripts/spx-mic-capture.sh` already contained the
proven recipe. Ported to
`tools/spx/boot-diagnostics/spx-mic-capture.sh`
(SHA256 `bce925bd0e18264035d712c9cdb48afd49e6387c98e05e691687d6d59bb01b1f`).
The two corrections versus the old probe:

* device is `plughw:0,1` — **MultiMedia2**, the frontend that has the capture
  backend routed — not `hw:0,0`;
* the mixer routing is applied first, and is what creates the DAPM path:

      MultiMedia2 Mixer SLIMBUS_0_TX = 1
      AIF1_CAP Mixer SLIM TX0         = 1
      CDC_IF TX0 MUX                 = DEC0
      ADC MUX0                       = DMIC
      DMIC MUX0                      = <source>

Route: DMICn/ADCn -> DEC0 -> SLIM TX0 -> AIF1_CAP -> SLIMBUS_0_TX -> MM2.

No kernel change, no module change, no device tree change and no reboot were
needed. This was reproduced on the live Y boot
`b5f0a540-3e81-4415-b08c-f869e01349a2`, kernel
`7.3.0-rc2-spx-mainline-20260927y+`, uptime ~13000 s.

The `parked[2][16]` capture-parking fix is present in this tree
(`sound/soc/qcom/qdsp6/q6asm-dai.c:111`), so the known close-wedge hazard
does not apply; `SPX: parking ASM capture session for DAI 1 across close` and
`SPX: reusing parked ASM capture session for DAI 1` were both observed.
`qcom-q6adm aprsvc:service@4:8: Failed to close copp -110` on close is
**expected and harmless** here — the copp is parked, not freed, and the next
run reuses it. This is already noted in the script header.

## Measured input map (2 s each, 48 kHz, mono, DEC0 gain 84)

| input  | RMS        | peak  | nonzero |
|--------|------------|-------|---------|
| DMIC0  | -78.6 dBFS |    27 |  82.9 % |
| DMIC1  | -75.5 dBFS |   134 |  81.8 % |
| DMIC2  | -107.1 dBFS|     9 |   0.1 % |
| DMIC3  | silent     |     0 |   0.0 % |
| DMIC4  | -127.1 dBFS|     1 |   0.0 % |
| DMIC5  | silent     |     0 |   0.0 % |
| ADC1   | -87.5 dBFS |    23 |  60.2 % |
| **ADC2** | **-63.3 dBFS** | **448** | 91.9 % |
| ADC3   | -83.8 dBFS |    10 |  75.8 % |
| ADC4   | -87.9 dBFS |     7 |  64.0 % |

DMIC0 and DMIC1 are the live built-in digital mics and are consistent with
memory `spx-dmic-micbias-gate.md` (Windows mics = WCD DMIC1 + DMIC0). DMIC3
and DMIC5 are digital-zero, i.e. not populated. `ADC2` is `AMIC2`, which the
device tree routes to **`"Headset Mic"`**; it is the loudest input, not an
internal mic. `Headphone Jack` and `Headset Mic Jack` both read `on`, which
on this codec is the no-headset-detected default (SPX reports jack presence
over ACPI, not the WCD comparator), so that reading is not independent
confirmation and ADC2's level needs physical interpretation.

## The floor is real, which is what makes the oracle useful

The quiet DMIC0 floor (-79.2 dBFS RMS, peak 27/32767) was checked
spectrally rather than assumed: 77 % of its energy is below 300 Hz, peaks sit
at 11.7 / 128.9 / 175.8 / 199.2 Hz, DC offset is -0.48, and the sample
histogram is a centred spread. That is genuine analog mic noise, not stuck
data and not a digital artifact. Repeat runs gave -79.0 dBFS (peak 30) and
-78.6 dBFS (peak 27), and per-second RMS varied (4.0 / 3.5 / 3.6 / 3.3), so
the channel is live and not frozen.

## Why this unblocks the two pre-declared candidates

Y's last playback used a 4000/32767 peak tone, i.e. **-18.3 dBFS** digital.
Against a **-79 dBFS** room floor that is about **61 dB of headroom**, so an
internal mic now discriminates a playing speaker from silence without a
listening report and without any new hardware.

Constraints for whoever uses it:

* use a **tone frequency above ~8 kHz** so the result is not ambiguous
  between speaker output and mechanical/handling noise, which is concentrated
  below 300 Hz;
* prefer the **speaker-side** DMIC over the `Headset Mic` ADC2;
* capture on **MM2 (`plughw:0,1`)**, never MM1 (`hw:0,0`);
* set the routing before every capture; it is runtime state and does not
  survive a reboot;
* **do not play audio without the user asking for that specific run**
  (memory `spx-no-unrequested-sound.md`). This session deliberately made no
  playback: the device clock read 00:25 local.

## State

Y is unmodified and remains live; `spx-known-good` is still the default.
Nothing was deployed, no GRUB entry was armed, and no reboot was performed.
