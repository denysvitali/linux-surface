# S02: missing sensor-processor driver match fixed; sensors not working

Recovery remains boot `1bdff3c9-f785-4613-bf23-4d137850bbb1`, kernel
`6.18.3-1-surface+`. No functional acceptance box closed. Battery tests are
deferred at the user's request.

**Changed:** commit `f72f8b91d05c` adds `qcom,sc8180x-slpi-pas` to the PAS
remoteproc driver, reusing the existing SM8150/SM8250 SLPI resource data.
The existing binding already groups those compatibles for five interrupts
and LCX/LMX power domains. No board node or guessed address was added.

**Established:** SQ2 `SEN2` depends on SCSS and FastRPC, separately from ADSP.
The saved Surface SCSS INF installs `qcslpi8180.mbn` with a 20 MiB reservation;
sensor configuration uses `libsdsprpc.dll`, and firmware strings name SDSP
SensorsPD/domain2. Audio-domain FastRPC is therefore not the missing sensor
transport. Recovery's advertised QRTR services contain neither SSC400 nor
SMGR256. Discovery was read-only and its device lock was released.

**Validation:** incremental `W=1` remoteproc module build passes in the fixed
build directory. The generated module exports the new OF aliases and retains
`7.3.0-rc2-spx-mainline-20261004bg+` vermagic. Checkpatch passes. An initial
single-module build failed dependency linking and omitted the release suffix;
the fixed release was restored before the successful dependency-aware build.
No module was installed/reloaded, and no boot, sound or capture occurred.

**Next:** establish the SLPI Q6 MMIO base, reserved-memory ownership and complete
IRQ/GLINK/FastRPC board wiring before enabling its node. SCSS ACPI exposes only
IRQ0x199; existing SMP2P declarations and LCX/LMX provider support are useful,
but not a complete remoteproc description. Once SSC400 is advertised,
[libssc](https://codeberg.org/DylanVanAssche/libssc) provides supported bounded
sensor requests; [hexagonrpcd](https://github.com/linux-msm/hexagonrpc) supports
SensorsPD and serving the saved sensor registry/configuration. S02 stays open.
