# Surface Pro X trial tool

Use `trial.py` for preparation, installation, one-shot boot and bounded return.
It reuses the completed kernel at
`/var/tmp/spx-mainline-trial-20261004bg/work-build` and keeps its release
`7.3.0-rc2-spx-mainline-20261004bg+` across attempts. Do not create another
source copy, tar, release suffix or per-attempt script.

The current non-audio feature test supplies the existing installation's
Bluetooth address to a copied DTB. Shared UC/PAS trial diagnostics stay off;
the WCD/SoundWire/speaker modules are blocked. No sound or capture runs.

```
sudo python3 -B tools/spx/trial.py prepare 20261004bg --address CE:27:F9:D2:B6:C9
sudo python3 -B tools/spx/trial.py install 20261004bg
sudo python3 -B tools/spx/trial.py boot 20261004bg
```

Preparation uses the existing full build, normal modules_install/depmod and
mkinitcpio. The generic `spx-trial-return@` units capture the kernel/journal
and return after900s. The known-good kernel/initramfs/DTB are checked before
selection/reboot; known-good stays the persistent default. Each attempt is
selected once. Results and short state files go to
`/var/lib/spx-boot-diagnostics/functional/<attempt>`.

The generic `spx-trial-check@` timer starts bounded functional checks at 50s:
RFCOMM socket and UHID open, controller state, a 25 MB IPv4 transfer over
`wlan0`, and battery/thermal/remoteproc/sensor readouts. It takes the device
lock and records `functional.json` incrementally. These are partial checks;
pairing, physical input, charging transitions and resume still need their
own functional tests. No sound or camera/microphone capture runs.

For a module change, commit it, build the driver against this fixed output,
then reload it on the running mainline kernel. For example, with the changed
driver directory assigned to `SPX_DRIVER_DIR`:

```
make -C /var/tmp/spx-mainline-trial-20261004bg/work-build \
  M="$SPX_DRIVER_DIR" MO=/var/tmp/spx-module-output ARCH=arm64 -j6 modules
```

The Bluetooth profile fragment enables RFCOMM, classic HIDP and BlueZ's
userspace HID transport as modules. It requires the existing Bluetooth,
BR/EDR and HID support. The coordinator applies it under the build lock,
retaining the current configuration, release and build directory:

```
SPX_BUILD=/var/tmp/spx-mainline-trial-20261004bg/work-build
scripts/kconfig/merge_config.sh -m -O "$SPX_BUILD" \
  "$SPX_BUILD/.config" tools/spx/functional.config
make -C "$SPX_BUILD" ARCH=arm64 olddefconfig
make -C "$SPX_BUILD" ARCH=arm64 -j6 modules
```

Check that all three fragment values remain `m` after `olddefconfig`. On the
same-release mainline kernel, install the new modules, run depmod, then load
`rfcomm`, `hidp` and `uhid`. An RFCOMM socket should open and `/dev/uhid`
should exist; restart Bluetooth while idle to retry profile registration.
N02 still needs an owned keyboard or mouse paired and used, reconnect and
suspend/resume with Wi-Fi active. Profile registration alone closes no box.

Install only the changed module and run depmod before reloading. Preserve the
active network and test state. Never unload MSM display modules. Reboot for
DTB, initramfs or built-in changes; ordinary driver tests should reuse the
running kernel. Venus remains parked.

After collecting a result, retire its boot directory, old module tree and
enabled timer instance, keeping the current candidate and known-good. Keep
the journals and one-page result. [Physical checks](boot-diagnostics/PHYSICAL-TESTS.md).

For speaker work, add `--audio` to preparation. This starts the native codecs
with amplifier enables low (`GPIO 0x1e/0x18`) and suppresses desktop audio and
old speaker bridges for that boot. `audio.py plan` is entirely offline.

After the user requests that specific listening run, use the existing trial
tool on the running candidate (substitute its attempt ID):

```
sudo python3 -B tools/spx/trial.py audio ATTEMPT --audio-action listen \
  --allow-amp-power --allow-playback
```

The test takes the device lock, checks native enumeration, sets minimum PA
gain, and opens one owned 48 kHz stereo PCM on digital silence. It verifies
physical left/right port mapping, bypassed companders and each codec's explicit
late initialization before playing two seconds left, right, then both. It
attempts to park both amplifiers before closing that PCM on every exit. No
microphone is captured. Amplifier startup can still produce static; minimum
gain does not establish that startup will be quiet. Read `audio/listen-result.json`
and obtain the person's listening result before deciding on another run.

The user's October 4 instruction authorizes an automated speaker/microphone
feedback loop and bounded retries without a human listening response. Use:

```
sudo python3 -B tools/spx/trial.py audio ATTEMPT --audio-action feedback \
  --allow-amp-power --allow-playback --allow-capture
```

To run automatically after the next trial starts, replace `audio` with
`arm-audio` before selecting the boot. The startup check consumes the request
once before accessing hardware. Add `--return-after-audio-seconds 120` to
schedule recovery two minutes after the test and log collection finish; the
original trial deadline still applies if startup never reaches the test.
BN passed this complete loop; see
[the recorded result](boot-diagnostics/RESULT-20261004bn.md).

The `desktop` audio action is the next bounded test, using the same three
authorization flags. It initializes one native PCM, then forwards a temporary,
explicitly selected PulseAudio sink at unity gain into that PCM. Finite desktop
application tones and a repeat after idle are measured through the internal
microphone. Each phase uses the fixed two seconds of quiet immediately before
its application; detection thresholds and tone levels are unchanged. Legacy
speaker bridges remain stopped. The temporary graph is
removed afterwards; this test does not install a persistent desktop bridge.
Unlike `feedback`'s amps-off control, normal desktop-test completion closes the
PCM while amps are still attached, verifies teardown, then powers them down.
Failures retain immediate amplifier powerdown. Read `audio/desktop-result.json`
for separate acoustic and teardown outcomes.
[BP passed both checks](boot-diagnostics/RESULT-20261004bp.md); WCD RX overflow
and ADM capture-close faults remain separate lifecycle issues.

For ordinary desktop playback, the `serve` action keeps the same initialized
PCM after verification and connects the existing `spx_speakers` output:

```
sudo python3 -B tools/spx/trial.py arm-audio ATTEMPT --audio-action serve \
  --serve-seconds 0 --return-after-audio-seconds 61 \
  --allow-amp-power --allow-playback --allow-capture
```

Zero means ordinary playback continues until the service stops. A positive
duration can still bound a specific application test.
Startup first verifies the bounded test applications and then the actual public
output through the microphone. Capture stops and its mixer routes are restored
before handoff. Read `audio/serve-ready.json` for that boot's readiness; also
check that its owning process and PCM remain alive. `serve-result.json` records
the initial/handoff state and, after exit, the final cleanup outcome.

Normal application audio preserves both channels with fixed digital attenuation
of 1433/32768 and minimum PA gain. This deliberately starts at a low volume;
the desktop slider starts at 100% within that output limit. It does not use
the obsolete bridge's 44-times amplification. The microphone
does not run during the application session. **An untimed audio bridge does
not cancel the boot fallback.** The coordinator must settle that boot policy
separately after readiness; failure or completion moves an active return timer
to the requested delay. A timed session extends the return beyond its end.
A normal stop closes the attached PCM before
parking, while errors park immediately. This does not change the default boot
entry or establish daily-use lifecycle reliability.

The `feedback` action holds one internal DMIC1 capture on MM2 across quiet, amplifier startup,
and the left/right/both sequence. It aborts on clipping, a large level increase,
capture stalls or ALSA failures; each requested tone must sustain for 0.4 seconds
above the same recording's quiet floor and neighboring frequencies. Residual
noise is checked separately. An amps-off playback control must remove the tones.
The thresholds are uncalibrated: a pass proves detected output, not physical
speaker placement, useful listening volume or desktop audio integration.
`capture` with `--allow-capture` runs only the quiet microphone check.
Private WAV files and sample-indexed phase scores accompany
`audio/feedback-result.json`. The capture process is finite, uses fixed PCM
geometry and disables ALSA's unsafe automatic XRUN recovery. Capture routes are
restored and amplifier powerdown is verified on exit. Do not run a second test
after an ASM mapping/close failure without resolving that DSP lifetime problem.

The late-init sysfs nodes are per native speaker; reported PA/protection
values are driver shadows, not physical register readback. The six-second
tone sequence and successful software checks alone do not pass A01.

If a failed teardown leaves the command FIFO occupied, use
`trial.py audio ATTEMPT --audio-action recover`. This requires both amplifiers
already off, desktop audio paused and no PCM/driver streams. The driver checks
those conditions and flushes only the command FIFO once; it does not reset the
bus or enable speakers. Read `audio/recover-result.json`. A module reload alone
does not clear retained FIFO state. Initialization now requires actual codec
`HW_INIT` completion; SoundWire attachment by itself is insufficient.
