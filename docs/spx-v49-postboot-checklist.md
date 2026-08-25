# SPX §49 post-boot checklist — v29 auto-cal RX0 test (armed 2026-08-24 ~22:00)

Armed entry: `spx-speaker-v29-acdb-cal` (one-time; persistent default remains
`spx-audio-rescue`). This boot's purpose is **listen-free and objective**:
§48.6 ladder #1 — does `q6afe.spx_auto_speaker_cal=1` (ADSP-native SLIM
channel config, delta #1) change the per-stream
"overflow error on RX port 0" signature (wcd934x.c dev_err_ratelimited)?

Deployed before this boot (§49 fleet output, all defaults legacy):
- `/lib/modules/$(uname -r)/updates/{snd-soc-wsa881x,soundwire-qcom,snd-soc-wcd934x,q6afe}.ko`
  (old copies kept as `.bak-pre49`; `sudo mkinitcpio -P` run).
- New knobs (all default off/-1, none armed on this cmdline):
  wsa881x spx_win_boost_loop_stab / spx_win_misc_ctl1 /
  spx_win_gain_singleshot / spx_win_teardown_reset;
  soundwire_qcom spx_idle_clk_stop_ms;
  q6afe spx_slim_slave_eaddr_lsw/_msw/spa..._pgd_la/_intfdev_la;
  wcd934x spx_pgd_rx_port_cfg.

## Steps

[0] Coherence: `grep -o "q6afe.spx_auto_speaker_cal=1" /proc/cmdline` must hit.
    `grep -o "spx_wsa_gpio_val=0x00" /proc/cmdline` must hit (guarded entry).
    Confirm new modules actually loaded:
    `cat /sys/module/q6afe/parameters/spx_auto_speaker_cal` -> 1 (Y?).
    `modinfo -p /lib/modules/$(uname -r)/updates/snd-soc-wsa881x.ko | grep -c spx_win_` >= 4.
    Power state record (rule): AC? battery %? charging?
    (`scripts/spx-power-snapshot.sh` or read /sys/class/power_supply/*).

[1] Autotest result: `journalctl -b -u spx-speaker-autotest.service --no-pager`.
    Expect guarded first stream completed (device-0 announce, cold-init replay,
    PA lifecycle, Q6 write_done>0 in close counters).

[2] PRIMARY METRIC — RX0 overflow counts per stream window:
    Stream-1 window: from autotest start to its tone end.
      journalctl -k -b | grep "overflow error on RX port 0"
    Baseline expectation (delta #1): fires ~once per stream WITHOUT cal.
    Compare stream-2 (next step) vs stream-1. Directional only (ratelimited).

[3] Second stream in same boot (valid since spx_keep_asm):
    `scripts/spx-play-right.sh` (or aplay 5 s S16 48k stereo), then re-grep
    overflow lines with timestamps; count per window. Also capture
    `q6asm_dai` close counters for both streams (submitted/write_done/fallback).

[4] Record everything into PROGRESS §49 follow-up note; do NOT draw quality
    conclusions without a listen (this boot is counter-evidence only).

[5] Housekeeping: next_entry was consumed by this boot; confirm
    `grub-editenv /boot/grub/grubenv list` shows saved_entry=spx-audio-rescue,
    next_entry empty. Remove /var/lib/spx-speaker-autotest/armed if still present.

## If the boot is silent/broken

Rollback = reboot into default `spx-audio-rescue` (untouched); modules can be
restored via the `.bak-pre49` copies + another `sudo mkinitcpio -P`. No DTB or
cmdline change is involved in the rollback path.

## RESULT (2026-08-24 22:01–22:30)

[0] OK — cmdline coherent, all §49 knobs present at legacy defaults; AC online,
    BAT 47 % not charging. [1] autotest status 0, `32/32/0`, attach proven.
[2] stream-1 RX0 overflow: 1 hit at uptime 49.868 = +80 ms after PA POST_PMD.
[3] stream-2 (`spx-play-right.sh /tmp/tune10.wav`): `40/40/0`, 1 hit at
    1050.400 = −9 ms before PA PRE_PMU. Baseline (08-22 v28, no cal): +72 ms
    after POST_PMD. => delta #1 NEGATIVE.
[4] Recorded in PROGRESS §49.1 + CLAUDE.md. Metric reclassified: the IRQ handler
    masks the port after the first hit (self-masking 0/1 flag at a port
    boundary, idle C0 channel) — not a static proxy.
[5] `next_entry` empty, `saved_entry=spx-audio-rescue`, `armed` consumed.
