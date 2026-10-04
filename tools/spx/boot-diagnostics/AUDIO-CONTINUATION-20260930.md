# Silent single-pin boot trial Z and corrected measurement

Y is still running on boot `b5f0a540-3e81-4415-b08c-f869e01349a2`.
Known-good remains the saved default, next_entry is empty and EFI BootNext is
absent. No playback is authorized by this continuation. Do not run a tone,
desktop playback or a PCM probe automatically.

## SD_N experiment

The 28 September candidate plan was a proposal, not an executable prepared
trial. Its `init=` mechanism is unnecessary and cannot guarantee the intended
ordering: the WCD device may not exist at that point, or its children may
already have probed when it does. Y's archived and installed `wcd934x.ko`
already has the read-only boot parameter `spx_wsa_en_pin`.
`drivers/mfd/wcd934x.c` applies that single-bit override after WCD bring-up
and before adding the GPIO, codec and SoundWire children. Z reuses Y's exact
kernel, modules, DTB and initramfs, adding only `wcd934x.spx_wsa_en_pin=1`
besides the attempt identifier. No live parameter change is needed.

The driver uses masked updates to set pin 1 direction and value, leaving pin 2
and every other bit unchanged. Expected software register state is direction
`0x02`, value `0x1a`, compared with Y's `0x00`/`0x18`. The raw two-pin override
parameters must remain `-1`, and DAC port swap must remain `N`.

The earlier SD_N state report overstates its evidence. This regmap uses
REGCACHE_MAPLE and GPIO registers are not volatile; both debugfs and gpiolib
may return cached values. An input's value register does not establish its
external electrical level. The claimed physical pin-low/amp-off diagnosis is
therefore a hypothesis. Also, the WSA runtime callbacks do drive the normal
GPIO descriptor in their `else if` branches; enumerated mode forbids runtime
autosuspend, while Surface probe deliberately preserves firmware levels.
These details explain the software input state without proving amp power.

The existing MFD override ignores update return codes. Its success log alone
is not proof. Archive the parameter values, GPIO direction/value view, WCD
register view, SoundWire status, errors and baseline before judging Z. Even a
clean pass establishes only this silent boot boundary; acoustic playback
requires a separately requested run. A negative acoustic result would not
prove that GPIO drive failed, nor justify stacking a DP4 change onto this trial.

## Spectral judge correction

The previous tool used one-sided FFT power without doubling interior bins;
it also called the largest of two high sub-bands the total high band. Correct
Parseval power is `sum(w[k] * abs(X[k])**2) / (m*N)`, with interior weight 2
and DC/Nyquist weight 1. The high band now sums every bin from 8 kHz through
Nyquist. A full-scale sine has RMS -3.01 dBFS, not -6 dBFS.

Reanalysis of the hash-verified archived captures gives combined high-band
levels DMIC0 **-87.6 dBFS**, DMIC1 **-83.2 dBFS**, ADC2 **-77.9 dBFS**.
The old -93.2 dBFS DMIC0 number is superseded. The recordings and their raw
RMS values are unchanged. Seven hardware-free tests cover sine calibration,
padded noise/DC, summed high bands, Nyquist, boundary leakage, empty/short
captures, silence and refusal to average stereo channels into cancellation.

A >20 dB rise is a measurement threshold, not validated acoustic sensitivity.
Digital playback amplitude cannot be subtracted from recorded microphone dBFS
to infer acoustic headroom. A requested tone must be identifiable, compared
with a contemporaneous quiet capture using the same channel, routing and gain;
the microphone's response to known acoustic sound remains to be demonstrated.
No absence of a high-band rise establishes speaker silence by itself.
