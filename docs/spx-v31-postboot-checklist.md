# V31 post-boot checklist (2026-08-22)

Armed before the reboot: `next_entry=spx-speaker-v31-fourport`, autotest `armed`
marker present, persistent default still `spx-audio-rescue`.

The one variable under test is `snd_soc_wsa881x.spx_stream_port_mask=5`
(DAC + BOOST descriptors) against the v28 DAC-only baseline. Rationale in
`PROGRESS.md` §32.

## 1. Confirm the intended boot actually happened

```sh
grep -o 'spx_stream_port_mask=[0-9]*' /proc/cmdline    # expect 5
grep -o 'spx_wsa_gpio_val=0x00' /proc/cmdline          # expect a match
sudo grub-editenv /boot/grub/grubenv list              # next_entry must be empty again
```

If `spx_stream_port_mask=1` appears, the one-time entry was not taken and the run
is void — re-arm rather than interpreting anything.

## 2. Read the guarded run

```sh
RUN=$(sudo ls -1dt /var/lib/spx-speaker-autotest/runs/* | head -1)
sudo cat "$RUN/exit-status"
sudo tail -60 "$RUN/service.log"
sudo grep -E 'active_ports=|SPX ASM stream|PA DAPM event|shadow (slave|master) DP|MCP_SLV_STATUS|overflow|XRUN' "$RUN/dmesg-after.log" | tail -40
```

Expected if the transport is healthy: `active_ports=2`, both master DP4 banks
`0x01000607`, slave DP1 **and** DP3 enable/disable shadows (the all-descriptor
bank shadow added to `qcom.c` for this test), `bits=16`, `submitted == write_done`,
`fallback=0`, PA PMU/PMD both seen, GPIO parked back to `0x00`, no fault.

## 3. The acoustic question

Compare against the v28 baseline, which is: startup clack, 440 Hz tone, **static
also audible during the three-second digital-zero prefix**.

- Static gone or clearly reduced → the starved BOOST descriptor was the source.
  Next: confirm with `scripts/spx-portmask-sweep.sh 1` (back to DAC-only) and then
  make mask 5 the default in `wsa881x.c` rather than a command-line knob.
- Unchanged → stay in this boot and sweep, no reboot needed:

```sh
./scripts/spx-portmask-sweep.sh 7 15 1        # DOUT superset, all four, control
SPX_BOOST_SWITCH=0 ./scripts/spx-portmask-sweep.sh 1   # other half: boost off
```

  Masks are live-switchable (0644, read at `hw_params`) and every stream renders
  since the `spx_keep_asm` fix, so all of these are valid measurements.

## 4. Rollback

Persistent default is already the working no-audio rescue entry, so a plain reboot
recovers. To undo the module change:

```sh
D=/lib/modules/$(uname -r)/updates
sudo cp -a $D/soundwire-qcom.ko.bak-v28-20260822-112032 $D/soundwire-qcom.ko
sudo mkinitcpio -P
```
