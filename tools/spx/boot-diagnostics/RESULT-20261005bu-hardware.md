# BU: quiet hardware checks and CPU scaling fix

Boot `48d25b6b-14bf-488f-97bd-916f0ded7ee4`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. No sound, microphone or camera test ran
in this round. The original desktop playback owner2343 remained RUNNING and
capture stayed closed. Future audio tests are limited to peak1433/minimum PA
for nighttime; the current stream was not restarted.

**CPU scaling works and is retained.** Both clusters were pinned at maximum
under `performance`. A20-second idle/load/recovery sequence with one nice19
worker per cluster passed: last10-second medians were300→1766.4→361.2MHz
and825.6→3148.8→825.6MHz. Both reached their minima after load; peak48.4°C.
`schedutil` remains active. Commit `665d78f10583` makes the existing trial
checker apply the already-intended schedutil default to reused kernels while
preserving other userspace-selected governors. Its installed helper confirmed
both current policies. This establishes scaling, not measured battery savings.

**5GHz Wi-Fi upload passed:** 10MiB of synthetic zeros over verified HTTPS,
HTTP200,0.444s (~189Mbit/s including connection overhead), with no new interface
errors/drops. The existing BU25MB download result is reused. Reconnect,2.4GHz,
long transfers and resume remain open.

**Light-sensor identity corrected:** only ID0x92 and revision0x91 were read at
the existing I2C0/0x39 client: **0xdc/0x41**, identifying TCS3430. The DT comment
was correct; its APDS9960 binding was not. That driver's integration timing
and channel labels do not describe this chip. A dedicated driver/DT fix is
being prepared. Motion sensors require the separate Qualcomm sensor-hub stack;
the known camera receiver analog-supply dependency remains unresolved.

**Power observation:** nine samples over120s report AC online,49%,7.670–7.671V,
14.72Wh unchanged and Not charging. No charge gain or discharge was observed;
a firmware charge limit is possible, not proven. Temperatures35.2–40.3°C,
GPU/GMU runtime suspended119.82/120s. ADSP/CDSP/modem remain running without
restart signatures, but earlier APR/COPP errors remain. P01/P02/P05/B04 stay
open; charger transitions need a person.

Evidence under `/var/lib/spx-boot-diagnostics/functional/20261005bu/`:
`power-readout/`, `cpu-scaling/`, `wifi-upload/`, `sensor-identity.json`.
Known-good remains default; runtime return is uptime3600 while hardware work
continues. No complete hardware acceptance category closes from these partial
checks. Next: correct ALS driver, then one quiet charger/sensor physical batch.
