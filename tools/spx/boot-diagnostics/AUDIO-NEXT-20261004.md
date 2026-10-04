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

Two gaps prevent blindly applying the memory's GPIO/late-init recipe:

- `drivers/mfd/wcd934x.c` masks GPIO direction/output overrides with `0x06`.
  Passing `0x1e` does not set bits 3/4. The existing `spx_wcd_gpio` helper has the
  same mask. An explicit opt-in mask change or the existing full-register
  `spx_vol_write` helper is needed to reproduce direction/output `0x1e/0x1e`.
  Keep `spx_wsa_en_pin=-1`; preserve default behavior for other runs.
- WSA's `spx_rearm_init` rejects active/prepared streams and targets one debug
  amp. It cannot replace the known stereo late replay. The retained
  `/var/tmp/spx-stereo-resume-20260908/b8-fullclock-ldo14e-status.sh` uses
  `spx_wsa_dapm_cycle.ko cold_init=1` with temporary broadcast writes after the
  runtime-clock switch. Its source is already in `drivers/spx_extras/`.

Next preparation: add an explicit audio mode to the reusable trial tool; adapt
the retained sequence to current card/device names and a fresh silent PCM stream;
establish both physical amps, frame 7, stereo DP1/DP4 offsets 1/6; replay init,
disable both companders, set minimum PA gain `0xc9`, and allow settling on digital
silence. The old scripts hardcode dead 6.18 PIDs and automatically capture a
microphone: do not execute them unchanged. `spx-speakers-up.sh` also retains the
obsolete one-pin configuration.

Once that concrete test is ready, ask for one bounded listening run: left tone,
right tone, then both, followed by parking both PAs. No microphone capture is
needed. Amplifier bring-up has previously emitted loud static independently of
volume settings; the user must explicitly authorize that run before power-up.
Cold-start dual enumeration and the required settling delay remain unproven.
