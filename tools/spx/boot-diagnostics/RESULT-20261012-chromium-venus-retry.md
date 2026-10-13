boxes closed: 3 of 47; newly closed: none.

# Authorized decoder-only Chromium retry

Boot93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d unchanged throughout;
kernel7.3.0-rc2-spx-mainline-20261004bg+, nativeIRQ candidatee294913022d2.
User explicitly authorized one live retry despite hang/reset risk; no reboot
command, encoder load, sound or camera/microphone capture. Coherent tested
core+decoder loaded with old-child-autoload barrier. Startup PAS/protection/
resume/core-init passed. NativeIRQ FFmpeg H2641080p probe:12 frames decoded,
zero errors,10 null output frames, exit0; session polling not needed for this.
Early capabilities command permission denied before udev ACL settled; later
/dev/video32 ACL allows dvitali and FFmpeg/Chromium open it normally. No ACL change.

Chromium152 native AcceleratedVideoDecoder gate: hardware decode enabled,
selects /dev/video32 V4L2StatefulVideoDecoder. Muted same local H264High1080p:
time0, readyState1, zero total/dropped frames after20s bounded fixture; no
CAPTURE configuration or successful playback. Preclose IRQ207 asleep,
decoder thread futex-wait and poll thread in ppoll, not original inst-lock
permanent deadlock. No reset. Browser close exits0; stream teardown reports
FLUSH0x211008 timeout SID0 state5 IRQcache0x4, CMD1623/1623 consumed,
MSG4321/4326 has five unread words. This is new queued-response/no delivery
evidence, not proof of the initial stall's exact packet/IRQ cause.

Both modules removed successfully, barrier removed, lock released; no force
unload/reboot. Teardown timeout means not a fully clean decoder lifecycle.
No new Venus OF/refcount/host crash recorded. Encoder remained absent;
persistent modules/browser flags unchanged. e294913 removes permanent cycle,
but does not deliver all asynchronous/session responses or fix playback.
User asks continuing fix; next measurement uses fresh browser-only diagnostic
budget (FFmpeg probe exhausted32lines beforebrowser in this trial). Event at
22:09:54 belongs FFmpeg, not browser22:10:24. No numeric constants changed.
Logs /var/tmp/spx-venus-chromium-retry-{init,browser,kernel,post}-20261012.log,
preclose stacks -preclose-20261012.txt and GPU -gpu-20261012.json.
