# USB-C DisplayPort: negotiation reported successful, host display path absent

Read-only live checks on 2026-10-04 at 23:27–23:30 CEST; no reboot.
Boot `ab15d0b8-0e5b-404b-a380-246b9878f4ca`, kernel `6.18.3-1-surface+`.
U03/U04 remain open: no external monitor output was demonstrated.

## Observed

- Both external controllers, `ae90000` and `ae98000`, are **disabled** in the
  live device tree. Only internal eDP `ae9a000` is bound. DRM exposes eDP-1
  and Writeback-1, with no external DP connector.
- The attached Lenovo 40B0 dock (`17ef:30b5`) reports **DP Alt Mode
  configuration successful**, SVID `0xff01`, in its USB Billboard capability.
  USB4 and Thunderbolt modes report configuration not attempted. The dock's
  USB3 hubs and `r8152` Ethernet driver are present. Billboard having no Linux
  interface driver is not evidence that DP mode negotiation failed.
- `/sys/class/typec` and `/sys/bus/typec/devices` are empty. ACPI reports
  `Interpreter disabled`; `ucsi_acpi` is built in but has no ACPI device here.
  No `pmic_glink.ucsi` auxiliary device or `PMIC_RTR_ADSP_APPS` RPMSG channel
  is present. Previous explicit channel creation failed with `ENXIO`.
- Installed `spx_hpd_inject` is **not loaded**. This boot's modules-load log
  records error 517 (`EPROBE_DEFER`); SSAM was unavailable until its subsequent
  live repair. Even loaded now, the module could not capture an external DP
  bridge while those controllers remain disabled.

## Module experiment

Compiled the missing generic `typec_displayport.ko` successfully against the
existing 6.18 build tree, under the build lock. The module's vermagic matches
the running kernel. Kernel configuration, release and boot files were unchanged.
The build needed a per-command feature define because the saved config has DP
alt-mode disabled:

```sh
sudo make -C ../linux-surface-kernel \
  M=/home/dvitali/Documents/git/linux-surface-kernel/drivers/usb/typec/altmodes \
  CONFIG_TYPEC_DP_ALTMODE=m KCFLAGS=-DCONFIG_TYPEC_DP_ALTMODE_MODULE=1 -j2 modules
```

The module is a build artifact, not installed or loaded. Live module testing
was deferred because the active audio coordinator held the device lock. No
load result or functional improvement is claimed. A generic alt-mode driver
binds to existing Type-C devices; it does not create the absent port or display
controller. See the [kernel Type-C API](https://docs.kernel.org/driver-api/usb/typec.html).

## Meaning and next step

The dock reports completed DP configuration, but this boot cannot send it video:
MSM initialized without either external DP controller. The earlier live DP0
overlay probed a controller after DPU startup but created no external connector;
rebinding DPU then froze the machine (LOCAL-PROGRESS T2). Do not repeat that.

The candidate already contains experimental `surface_aggregator_usbc` forwarding
and enabled DP0. When that kernel is run under separately authorized work, load
the forwarding module after display/SSAM startup, then request one dock replug
and check actual monitor output. No reboot is requested or scheduled here.
Initial-state replay, PHY orientation and second-port routing remain incomplete;
the old forwarding module also incorrectly routes both ports to its first bridge.
