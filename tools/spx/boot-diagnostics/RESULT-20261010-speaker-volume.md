boxes closed: 3 of 47; newly closed: none.

# Ordinary desktop volume ceiling

Boot `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Problem:** user hears both speakers but reports very quiet output even at
100%. GNOME gain was 0 dB; the feeder still attenuated all samples by
1433/32768 (4.37%, approximately -27.2 dB). WCD RX7 was also at 0 dB;
the slider could not remove the feeder attenuation.

**Change:** user explicitly requests higher ordinary listening volume.
`play-desktop` now defaults to peak12000 rather than peak1433, raising its
ceiling by 18.46 dB (8.37x sample amplitude). This uses the already-supported
36.62% maximum, with no software gain above unity. Diagnostic modes retain
peak1433 and minimum PA gain; no automatic tones or microphone recording.
The 4096-byte pipes, 20 ms monitor queue and retained DSP geometry are unchanged.

**Application:** stopped the quiet feeder; physical amps parked and FIFO zero.
As before, desktop service stopping needed a separate explicit stop after the
helper reported a cleanup error. Restarted native play-desktop on the same
boot using the new default. Runtime service only; reboot startup remains open.
Four existing peak-related offline tests pass. Runtime status verifies
peak12000, both PA gains 0, default sink 100%, and native PCM running.
User confirms: "That is louder." This confirms a useful increase, not factory
maximum, calibrated balance or distortion limits; full A01/A03 remain open.
Latency remains unresolved. No further increase made for the user's question
about factory maximum.

**Full digital range, subsequently requested by user:** play-desktop now defaults
to peak32768/unity gain, another +8.73 dB above12000. Ordinary full-scale stereo
samples preserve both channels and signed extrema in the offline pipe test.
Serve/acoustic modes keep the previous12000 ceiling and quiet1433 default.
Both PA gains remain0; no extra automatic sound or capture. The user can now
control the full digital range through GNOME's output slider or volume keys.
This does not establish the factory acoustic maximum or increase PA gain.
Five focused offline tests pass. Startup persistence and latency remain open.
