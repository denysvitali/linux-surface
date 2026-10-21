boxes closed: 3 of 47; newly closed: none

# DP stream preparation: preserve retraining failure (WIP)

Last verified automatic functional **24/49**, inventory **42/52**, blocked **35**,
failed **0**, errors **0**, boot `32ec6625-df7d-431a-8376-d4cdbd4d5e7d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`:
[boot report](/var/lib/spx-boot-diagnostics/boots/32ec6625-df7d-431a-8376-d4cdbd4d5e7d/hw-validation/report.json).
Connected-display rerun is in progress; the prior counts are not its result.

**Defect / correction:** `msm_dp_ctrl_prepare_stream_on()` called
`msm_dp_ctrl_link_retrain()` without retaining its error. After failed forced
or channel-equalization retraining, stream preparation therefore returned zero,
permitting video startup on an untrained link. Preserve the error and enter
existing mainlink teardown after clearing the training pattern. The caller
already aborts stream startup when preparation fails. Successful paths remain
unchanged. The 6.18 implementation also discards its retrain return.

**Offline evidence:** the test compiles the real C helper with controlled
hardware callbacks. Before correction, a forced retrain returning `-ETIMEDOUT`
incorrectly returns success. After correction, five new cases pass: forced
failure, failed channel-equalization retrain, both successful retrain paths,
and no retrain needed. All sixteen cases in `test_dp_training.py` pass.
Full incremental modules build compiles `dp_ctrl.o`, links `msm.o` and
`msm.ko`, and passes MODPOST. Vermagic matches the running release.
Checkpatch and diff checks pass. Build log:
`/var/tmp/spx-dp-retrain-modules-build.log`.

**Hardware scope / next trial:** the user connected the external display again
at 02:14 CEST. Baseline journal has a new USC HPD IRQ `-110`; preserve this
boot's report and journal before booting a candidate. The earlier incident's
`-104` preparation failure came from initial training, before this helper;
it does not implicate this discarded-retrain path or prove a panic cause.
One-shot attempt `20261021dr` will use the linked MSM candidate (AUX guard,
retry-exhaustion and retrain-return fixes), unchanged Image/DTB/root modules,
automatic return to `spx-mainline`, and mandatory no-capture validation.
No live MSM reload/unbind, synthetic hotplug or modeset test. Active internal
and external scanout can establish connected-display regression behavior;
unexercised error branches and the original AUX/panic cause remain open.
