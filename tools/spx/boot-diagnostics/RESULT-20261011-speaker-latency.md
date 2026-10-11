boxes closed: 3 of 47; newly closed: none.

# Desktop speakers: 10 ms periods and +9 dB amplifier gain

Boot `298cf388-134f-4db3-a218-413f5af213d3`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. No reboot, no module reload, no test
tones, no microphone capture.

**Problem:** user reports low volume and a considerable delay.

**Found:** the amplifiers ran at PA step 2 of 12 (+3 dB); Windows writes gain
code 0 (+18 dB, register mode). Playback used 2400-frame periods: about 100 ms
queued in the ALSA ring, up to 50 ms in aplay's chunking and 50 ms in flight to
the DSP, plus a Python per-sample loop (about 55% of one core). The retained
MultiMedia1 session cannot change geometry: a reused client keeps its mapped
9600-byte buffer layout until reboot.

**Changed:** `pcm_feed.c` (`spx-pcm-feed`) replaces aplay for `play-desktop
--feeder`. It never lets the PCM stop (the retained session rejects a second
prepare), pads with silence, holds the ring at 2 periods plus half a period,
and takes `parec` on stdin directly. `--pcm-device` selects the front end;
MultiMedia2 had no session on this boot, so it took 480 x 8 frames live.
PA gain steps 0..12 are accepted; `/etc/spx/speaker-gain-step` is now 6.

**Observed:** MultiMedia2 480-frame periods complete every 10 to 12 ms;
5927/5927 buffers submitted/completed, fallback 0, on the first run. Ring fill
1200 to 1904 frames (25 to 40 ms), no underruns, no corrections after startup
over one minute. Both PA mixers read 6. Service CPU about 3% each for Python and
the feeder. The first attempt failed on a feeder bug (explicit prepare after
hw_params, EBUSY); amplifiers stayed parked.

**Not established:** acoustic latency was not measured and the user has not yet
judged delay or loudness. DSP-internal delay is unmeasured. Distortion at +9 dB
and above is unassessed; there is no speaker protection. A01/A03 stay open.

**Next:** user listens. This boot uses a runtime drop-in for MultiMedia2
(`/run/systemd/system/spx-desktop-playback.service.d/lowlatency.conf`); the
installed unit uses the feeder on MultiMedia1, which is untested until the
next boot. If delay is still noticeable: 240-frame periods, then the DSP
low-latency stream mode (kernel, needs a trial boot).
