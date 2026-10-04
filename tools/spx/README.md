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

For a module change, commit it, build the driver against this fixed output,
then reload it on the running mainline kernel. For example, with the changed
driver directory assigned to `SPX_DRIVER_DIR`:

```
make -C /var/tmp/spx-mainline-trial-20261004bg/work-build \
  M="$SPX_DRIVER_DIR" MO=/var/tmp/spx-module-output ARCH=arm64 -j6 modules
```

Install only the changed module and run depmod before reloading. Preserve the
active network and test state. Never unload MSM display modules. Reboot for
DTB, initramfs or built-in changes; ordinary driver tests should reuse the
running kernel. Venus remains parked.

After collecting a result, retire its boot directory, old module tree and
enabled timer instance, keeping the current candidate and known-good. Keep
the journals and one-page result. [Physical checks](boot-diagnostics/PHYSICAL-TESTS.md).
