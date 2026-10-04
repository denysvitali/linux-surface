# Internal speakers after BJ

**BJ passed native initialization of both amplifiers** at separate addresses,
followed by verified powerdown. See [the result](RESULT-20261004bj.md). Playback
remains untested. The authorized identity run is finished; the amplifiers are off.

BI deliberately blocked the internal audio drivers and exposed only dock USB
audio. BJ removed that blacklist and registered the internal Surface Pro X card.
The user's authorization covered BJ's completed identity test; audible playback
needs its own requested run after preparation.

The known baseline is the sibling tree's
`docs/audio/2026-09-08-clean-stereo.md`, a successful live repair, not a repeatable
cold-boot setup. Mainline already contains the audio primitives and the board's
LDO14E 1.8 V always-on vote. Do not return to single-amp experiments.

The retained GPIO/late-init recipe has these adaptations:

- `5f0155537be2` adds an explicit SPX GPIO mask, retaining the default `0x06`.
  BJ opts into `0x1e` with direction/output `0x1e/0x18`: pins 3/4 high, both
  amplifier enables low. `spx_wsa_en_pin=-1` disables the legacy one-pin override.
- WSA's `spx_rearm_init` rejects active/prepared streams and targets one debug
  amp. `94d48470830e` adds per-native-slave `spx_late_init`, requiring a prepared
  DAC-only stream and minimum PA gain; it cycles that codec's DAPM pin and
  propagates codec write failures. Reported PA/protection values are shadows.
- `432b8793466f` maps physical unit3/left to DP1 and unit4/right to DP4,
  independently of the assigned bus address. `7469b5f09155` extends the master
  snapshot with both port banks and fresh WCD compander/volume register reads.

BJ uses the reusable trial tool's parked audio mode. Automatic desktop audio and
legacy bridges are disabled for that boot. A separate, explicitly authorized
`audio --audio-action initialize --allow-amp-power` run holds the discovered
SoundWire master awake, powers pin 1 then pin 2, and compares native devices with
physical identities at distinct addresses. It uses a five-second polling budget
per stage and attempts amplifier powerdown on every exit. This opens no PCM.
BJ passed this sequence after live module reloads and restoring parked output.
An unattended cold boot remains unverified; this does not close A01.

`audio.py listen` now owns a fresh silent PCM stream and verifies frame7/bank0,
stereo DP1/DP4 offsets1/6, late init after the runtime clock switch, both
companders bypassed, minimum PA gain `0xc9`, then one second of digital-silence
settling. This chosen delay has not been validated as sufficient on a fresh boot.
The old scripts hardcode dead 6.18 PIDs
and automatically capture a microphone: do not execute them unchanged. Their
helper also copies a stale private controller layout. `spx-speakers-up.sh`
retains the obsolete one-pin configuration.

After the parked candidate starts, ask for one bounded listening run: two seconds
left tone, right tone, then both, followed by parking both PAs. No microphone capture is
needed. Amplifier bring-up has previously emitted loud static independently of
volume settings; the user must explicitly authorize that run before power-up.
Unattended cold-start setup and the required settling delay remain unproven.
