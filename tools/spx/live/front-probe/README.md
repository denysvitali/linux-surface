# Surface Pro X front camera live enablement

The overlay restores the OV5693 endpoint and its CSIPHY0 connection on the
existing mainline baseline, with the user-confirmed 180-degree mounting.
It changes only the running tree. It does not change the next boot's DTB.
The `ov5693.c` symlink builds the repository driver against the same kernel.

Build under the build lock, keeping the running release name:

```
sudo make -C /var/tmp/spx-mainline-trial-20261004bg/work-build LOCALVERSION=+ M="$PWD/tools/spx/live/front-probe" modules
```

The coordinator must hold the device lock and check that no camera/video
node is open before loading or removing this overlay. Unload `qcom_camss`
and `ov5693` first. Load the overlay, the sensor driver (with `v4l2_cci`
available), then CAMSS. Allow deferred sensor probing to finish before
opening the camera. Do not reload display or audio modules.

For removal, stop and close every camera client, unload CAMSS and OV5693,
then remove `spx_front_enable`; reload CAMSS to restore the rear/IR graph.
The kernel reports its existing overlay status-property leak warning on
apply; do not repeatedly apply/remove the overlay as a test.

Current result: `RESULT-20261010-camera-status.md` in boot-diagnostics.
The front streams real processed scenes, including binned output with both
flips. Startup uses ordered sensor supplies; cold-boot verification and
system suspend/resume remain open. The front graph is not yet deployed to
the persistent boot DTB. No checklist acceptance is implied.
