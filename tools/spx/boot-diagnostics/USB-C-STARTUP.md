# USB-C startup: bounded next trial (2026-10-05)

U02–U04 remain open. The user has no physical access; no dock replug or
monitor observation can be claimed.

Runtime collection is now in [RESULT-BZ](RESULT-20261005bz.md): the attached
dock supplies real boot events and GNOME activates external scanout without
a requested replug. This is one observed startup, not complete hotplug coverage.

`acfff8e5bc5a` replaces the forwarder's one-shot platform probe with a
driver/device registration that supports deferred probing. Missing SSAM,
DP0 supplier binding, DRM attachment or HPD callback now defer; disabled DP0
and the wrong connector type remain permanent failures. The existing event
forwarding and sequenced ACK are unchanged. No live MSM component is reloaded.

BZ (`20261005bz`) uses the fixed `7.3.0-rc2-spx-mainline-20261004bg+` build.
The module was built from `spx/wip/usbc-startup` in the existing output with
matching vermagic. `trial.py prepare --usbc` includes it in the early load
list; preparation, depmod, initramfs generation and GRUB syntax pass. These
are preparation observations, not functional acceptance. No audio/capture
request is queued. Known-good stays default; automatic return is 900 seconds.

After boot, inspect the forwarder's driver binding and startup journal,
DP/eDP connector state and kernel errors, then collect the result before
another experiment. Successful subscription only proves startup. Actual EDID,
link training and visible output still need a supported dock and monitor.

The 6.18 `deploy/spx-hpd-inject/spx_hpd_inject.c` only consumes events;
its reprobe knob synthesizes HPD, not a fresh state query. Saved SQ2 DSDT
`UPAN` and `UCS0` describe a software-filled notification mailbox, with no
documented USC GET command. QMP has a Type-C orientation switch API and the
Lenovo SC8180X DT shows graph wiring, but raw USC orientation and DP lane-mode
semantics are unproven. Do not guess commands, mailbox writes or PHY mappings.
