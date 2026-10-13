boxes closed: 3 of 47; newly closed: none.

# Installed Chromium H264 decode: handoff

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. Read-only reconciliation after an
interruption: another coordinator completed commit `ed636807cb13` and holds
the device lock. No competing live test, module action or reboot was run.

The fix is in Venus: native Iris1 firmware needs CODECCONFIG on standalone
SPS/PPS/SEI input. The driver flags those buffers, leaves picture-containing
buffers unflagged, and omits header-only entries from picture timestamp
tracking. Installed Chromium152 does not require rebuilding for this fix.

Confirmed current state: Venus core+decoder loaded; compatibility parameter
is `Y`; corrected modules installed in the running release's module tree;
`~/.config/chromium-flags.conf` contains
`--enable-features=AcceleratedVideoDecoder`. Encoder remains blocked by
`/etc/modprobe.d/spx-venus-decoder-only.conf`.

Saved verification from the owning coordinator:
- Standard launcher: GPU status `video_decode=enabled`; V4L2 decoder receives
  SOURCE_CHANGE, selects NV12 1920x1088, and initializes CAPTURE buffers.
  Playback reaches19.54 seconds /589 frames /1 dropped at1920x1080.
- Sustained run: video time advances15.39 to135.32 seconds over120 seconds;
  frame count rises463 to4063, dropped count12 to45.
- Reopen:19.38 seconds /584 frames /2 dropped at1920x1080.

Evidence: `/var/tmp/spx-venus-standard-launch-{gpu,playback}-20261013.json`,
`/var/tmp/spx-venus-standard-launch-browser-20261013.log`,
`/var/tmp/spx-venus-sei-config-{sustained,reopen}-20261013.json`.
These establish actual H264 decoding and reopen on this boot, beyond the
status flag. No post-reboot validation is claimed. D03 remains open for full
codec/encoder coverage; human checks remain deferred until the end.

The next normal Chromium launch reads the persistent gate. Any older browser
process must exit completely before relaunching to pick up changed flags.
