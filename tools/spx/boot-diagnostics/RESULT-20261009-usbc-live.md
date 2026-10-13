boxes closed: 3 of 47; IDs closed since last report: none.

# USB-C Alt Mode restored live

Boot `29923cc8-d3dd-4fd6-8400-e73cfbe6b5ca`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Cause:** this FI boot had neither the DP0 controller enabled nor
`surface_aggregator_usbc` loaded. The external DRM connector was disconnected.
The running MSM driver already exported the external HPD-IRQ handler, so the
missing piece was starting the existing DP0 and USC forwarding path.

**Fix:** built `tools/spx/live/spx_dp0_enable.ko` against this kernel with
`sudo make -C tools/spx/live`, then ran:

```sh
sudo insmod tools/spx/live/spx_dp0_enable.ko
sudo modprobe surface_aggregator_usbc phy_orientation=1
```

The first command applied the DP0 device-tree overlay, and the controller
bound to `msm-dp-display`. The second loaded the USC forwarder. Real port-zero events
applied normal orientation and reported DP pin assignment 4; DP-1 became
connected and exposed the monitor's modes. The user confirmed the display lit.
No synthetic event or physical replug was used.

**Meaning/next:** the current attached display works. This live overlay and
module load do not persist across reboot. U03 remains open for physical replug,
port/orientation and resume coverage. No checklist box closed.
