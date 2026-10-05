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

**October6 follow-up:** PAS never maps the Q6 register resource. Its earlier
MMIO blocker was descriptive, not a runtime dependency. All21 SLPI LOAD
segments carry relocation bit27; dynamic20MiB/1MiB-aligned no-map memory below
4GiB avoids the ELF range, which overlaps the current ADSP reservation.
3c1001ac3ac8 adds that reservation and secure-PAS node, with ACPI watchdog
GSI409/SPI377, existing Q6 family SMP2P bits and LCX/LMX. Handshake reuse needs
trial validation. No guessed register address is supplied.

Consumed Windows `qcglink8180.sys` dsps table row RVA0x2e690/file0x2d490
proves host3, IPC0x17c0000c/bit24 and GSI202/SPI170; consumer0x13c04–0x13c34.
535562d2de53 adds this GLINK edge. Firmware contains `fastrpcglink-apps-dsp`;
FastRPC context banks and user-domain setup remain separate. CH is installed
for a boot/QRTR discovery test, with the working CG kernel/modules and900s
return. Reused initramfs excludes the newer compiled USB IRQ experiment.
DT syntax/build pass; full schema tools are unavailable locally. S02 stays open
until actual sensor streams and response are verified. No capture or battery
measurements are part of this trial.
