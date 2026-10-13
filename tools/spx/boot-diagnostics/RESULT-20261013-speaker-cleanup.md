boxes closed: 3 of 47; newly closed: none.

# Native speaker service failure: offline cleanup correction

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel `7.3.0-rc2-spx-mainline-20261004bg+`;
no live playback, amp power/gain change, PCM reopen, mic/camera capture or reboot.

**Observed:** service started successfully and ran12h19m, not a boot startup
failure. It exited09:49 with `OSError: [Errno5] Input/output error`; saved native
feeder counters include31 underruns and42000 drift corrections. The saved PCM
log is empty; background monitor/feeder error fields are null. Cleanup parked
both amps and restored the graph, but also reported
`DirectMonitor object has no attribute stop`. The direct low-latency monitor
is process-backed, not the threaded monitor and has no stop event.

**Changed:** pre-parking cleanup signals only `DesktopMonitor.stop`; existing
later `graph.close()` still closes either monitor type after amp parking.
No DSP teardown, gain, routing, buffering or restart policy was changed.
Initial119-test offline audio suite passed. Changed failure-reporting tests pass.
After the diagnostic,118/119 pass; one existing bursty timing fixture fails its
zero-underrun assertion twice (10 then1), with waveform bytes still exact.
No oracle, playback buffering or watchdog setting was changed to hide this.
No sound/capture occurred (all fixtures mocked). This fixes a secondary cleanup
exception, not the primaryEIO or audio playback.

**Remaining lead:** periodic `check_stereo -> state()` reads SoundWire
`spx_audio_state`; its bridge/canary/FIFO failures return exactlyEIO. That is a
matching source path, not a proved failure cause. Native feeder failures instead
normally log stderr and surface RuntimeError; cumulative underruns do not locate
the09:49 failure. Result JSON now records traceback basename/function/line and
OSError errno (no locals/samples), preserving the original fatal error/parking.
The script diagnostic is installed while the service stays stopped, for the
next separately authorized start/normal boot;
no primary correction, retry or health-check relaxation is justified yet.
No safe playback retry is authorized by this generic continuation. Retain
parked mappings; no automatic restart or new audio test variants.
Current hardware validation remains11/40 functional,36inventory,44blocked,
1failed,0errors: native speaker service remains failed.
