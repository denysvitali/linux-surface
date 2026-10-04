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

The late-init sysfs nodes are per native speaker; reported PA/protection
values are driver shadows, not physical register readback. The six-second
tone sequence and successful software checks alone do not pass A01.
