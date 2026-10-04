# Internal speakers after BI

BI's silent speakers are expected: its kernel command line blacklists `wcd934x`,
`soundwire_qcom`, `snd_soc_wsa881x` and `snd_soc_wcd934x`. Only the ThinkPad
Thunderbolt 4 Dock USB audio card is exposed. This kernel blacklist cannot be
overridden by live modprobe. A separately prepared audio-enabled boot is needed;
no amplifier power or playback has been authorized for it yet.

The known baseline is the sibling tree's
`docs/audio/2026-09-08-clean-stereo.md`, a successful live repair, not a repeatable
cold-boot setup. Mainline already contains the audio primitives and the board's
LDO14E 1.8 V always-on vote. Do not return to single-amp experiments.

The retained GPIO/late-init recipe needs these adaptations:

- `5f0155537be2` adds an explicit SPX GPIO mask, retaining the default `0x06`.
  BJ opts into `0x1e` with direction/output `0x1e/0x18`: pins 3/4 high, both
  amplifier enables low. `spx_wsa_en_pin=-1` disables the legacy one-pin override.
- WSA's `spx_rearm_init` rejects active/prepared streams and targets one debug
  amp. It cannot replace the known stereo late replay. The retained
  `/var/tmp/spx-stereo-resume-20260908/b8-fullclock-ldo14e-status.sh` uses
  `spx_wsa_dapm_cycle.ko cold_init=1` with temporary broadcast writes after the
  runtime-clock switch. Its source is already in `drivers/spx_extras/`.

BJ uses the reusable trial tool's parked audio mode. Automatic desktop audio and
legacy bridges are disabled for that boot. A separate, explicitly authorized
`audio --audio-action initialize --allow-amp-power` run holds the discovered
SoundWire master awake, powers pin 1 then pin 2, and compares native devices with
physical identities at distinct addresses. It uses a five-second polling budget
per stage and attempts amplifier powerdown on every exit. This opens no PCM.
Native cold-start enumeration remains unverified; a build is not an A01 pass.

After native enumeration works, adapt the retained sequence to current device
names and a fresh silent PCM stream: frame 7, stereo DP1/DP4 offsets 1/6, late
init after the runtime clock switch, both companders bypassed, minimum PA gain
`0xc9`, then settling on digital silence. The old scripts hardcode dead 6.18 PIDs
and automatically capture a microphone: do not execute them unchanged. Their
helper also copies a stale private controller layout. `spx-speakers-up.sh`
retains the obsolete one-pin configuration.

Once playback preparation is ready, ask for one bounded listening run: left tone,
right tone, then both, followed by parking both PAs. No microphone capture is
needed. Amplifier bring-up has previously emitted loud static independently of
volume settings; the user must explicitly authorize that run before power-up.
Cold-start dual enumeration and the required settling delay remain unproven.
