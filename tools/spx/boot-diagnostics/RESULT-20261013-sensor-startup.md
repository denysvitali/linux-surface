boxes closed: 3 of 47; newly closed: none.

# Sensor provider startup ordering

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel `7.3.0-rc2-spx-mainline-20261004bg+`; unchanged,
no reboot, kernel/DT/module change, SLPI reset, sound or camera/mic capture.

**Cause/change:** the old provider started at33.953026s, before secure SDSP
udev initialization34.864952s/device activation35.000400s. Its closed systemd
BPF device filter was built without the not-yet-existing path; daemon open
failedEPERM before any SensorsPD attachment. The supervisor's later path wait
cannot rebuild that filter. SDSP is ordinary `qcom,fastrpc`; the separate
CAP_SYS_ADMIN-guarded CDSP path is disabled, so changing privileges is wrong.
Require and order `dev-fastrpc\x2dsdsp\x2dsecure.device` in the provider unit.
Keep empty capabilities, exact device allow, no retries and retained host.
Fix committed `79d4b25d0b65`, installed without a reboot.

**Observed:** with no prior attachment/client, one corrected service start
reachedREADY. Provider180855 retains initial host180867; proxy180944 is active.
Native existing3s streams: accelerometer84, gyroscope74, magnetometer38 finite
XYZ samples; all exit0 and acknowledge disable. The host/provider remain
unchanged and there are no new FastRPC faults, channel removal or heap restore.
SensorProxy advertises accelerometer support; compass interface and ambient
light support are not advertised on this daemon. Mount-matrix identity fallback
and read-only registry remain; no physical axes/calibration judgement is made.
Only aggregate stream counts were retained, not raw samples/protocol logs.

**Automatic coverage:** the existing `sensors.motion-read` row now exercises
those three proven SSC streams, requiring an already running provider, finite
measurements, enable/disable acknowledgements and unchanged provider identity.
It never starts/restarts the host or DSP. Whole-catalog live result:
**11/40 functional passes**,36/52 inventory observations,44 blocked,1 failed,
0 errors. Its actual motion counts are89/69/29; enable/disable ACKs and unchanged
provider verified. Sensor backend failure is gone; only speaker service failure
remains. JSON/Markdown/runner status and generated checklist updated under
`/var/lib/spx-boot-diagnostics/boots/93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d/hw-validation/`.

**Meaning/next:** the initial provider open failure is repaired in place; the
startup-order correction on a subsequent actual boot is unverified. S02 full
physical acceptance stays open; manual checks are not automatic prerequisites.
Next recorded failure is native desktop speaker startup; do not restart/play
or alter parked DSP mappings without its scoped safety proof/authorization.
No hardware tuning changed. Stream bounds reused:3s per sensor,12s process
ceiling,2s forced-cleanup allowance,>=20 finite samples; not sustained/resume
or calibration acceptance. Unit offline tests and systemd verification pass.
