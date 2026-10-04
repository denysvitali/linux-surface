# Independent N preparation review — 2026-09-22

**N's prepared state passed independent read-only review at M uptime
1316.58–1320.25 seconds.** The origin boot remained
`5306363a-95b7-4d6c-b93f-c85118fdf8a5`, release
`7.3.0-rc2-spx-mainline-20260922l+`. N had not been selected and has no
hardware result. The checker made no service, timer, device, parameter or
boot-selection changes.

[M's completed result](RESULT-20260922m.md) covers **734.11 seconds** without
a recovery return. The checker independently rehashed all **288 result
files**, verified exact manifest coverage and validated the immutable proof:

```
bae83eac8a7dceafee26dffd0db6609362e89ea38cbc64da263b144899b97b38
```

N's global and per-attempt manifests agree and pin that proof with the correct
origin boot, release, attempt and result path. Prepared preflight names the
same validated origin. This now satisfies the completed-M prerequisite in
[the exact-L audio review](AUDIO-STAGE5-L-REVIEW-20260922.md); M's successful
input enumeration still does not establish physical operation or reliable
startup across repeated boots.

## Exact reuse and command line

All **937 copied build files** match the unchanged L/M build manifest with
exact coverage, and all **272 symlinks** match M. All **202 installed
module-tree files**, including **187 modules**, match the copied manifest;
each module's vermagic names L. Source commit, current configuration and
archived source diff agree with the reused build. Only the explicitly allowed
README/component-status tracked documentation differs from the original L
snapshot. The build and extraction directories are private; the archived
initramfs is mode 0600. This makes no 0600 claim for deployed VFAT files.

All three installed payloads, three recovery files and eleven runtime files
match M's unchanged hashes. Payloads remain under `/boot/spx-trial-20260922l/`:

| Payload | SHA-256 |
| --- | --- |
| Kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

There is no N payload slot, rebuild, module installation or slot retirement.
The exact ordered command line changes only `spx_attempt=20260922m` to
`spx_attempt=20260922n`, stage 4 to stage 5, and appends
`slim_qcom_ngd_ctrl.spx_stage5_step=0`. Every critical selector occurs once,
including unchanged `spi_hid.startup_diag=0`, pin-after-QMI 1 and the
600-second window. Regenerating the GRUB entry from the manifest reproduces
`entry.cfg` exactly. The custom configuration contains that single entry;
both GRUB configurations pass syntax checking. Main `grub.cfg` is unchanged
and retains `spx-known-good` as persistent default.

The unchanged NGD source blob is
`f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`, SHA-256
`ac5977296b408d6096b67675f4e1ff1b1267a796bb3d57e55abf33cddb1a392b`.
The verified NGD module SHA-256 is
`31df6e27e5f8058dd9ff33bf2320cd38dc5e5a6ea4049771b72179210b380f1d`.
The [source review](AUDIO-STAGE5-L-REVIEW-20260922.md) therefore applies to
these exact prepared artifacts: step 0 adds INT_STAT and INT_EN reads to
the four stage-4 reads, with no explicit synchronous MMIO writes. The two
new reads have unspecified relative order. QMI still changes firmware
state, and runtime/IRQ/cleanup paths retain the documented limitations.
Stage-5 step 3 and interrupt enablement remain excluded.

## Origin state and one-shot boundary

Live M still has diagnostic parameter N, mode 0444, audio stage 4, all
substeps zero, pin Y/refcount 1 and all DMA, INT_EN, full-controller, PIO,
window-dump, PDR, bypass and PIO-debug guards N. Selection, response-type,
base-offset, DMA-mask and poll-RX values match the reviewed baseline. The
child is runtime-suspended with active time 0 and control auto. The prepared
stage-5 selector has not changed the running stage-4 module.

The early logger, return timers and evidence service are enabled; periodic
evidence collection is active. Origin return timers are inactive. A native
Happy query validated the existing session/thread, automatic continuation
message, workspace and host process arguments without printing or retaining
raw metadata. The copied M continuation acknowledgment matches its source.

The archived preparation helper SHA-256 is
`edfa847ce1fb617d7a9af441d916a4426387f848fc3ac787192e55d9e3d1b5bc`;
generated queue SHA-256 is
`0ce17754906cd0a8b00764e5daa1528655260ee133ecb26e9338700825a1276f`.
Both equal the separately reviewed versions. The queue compiles and retains
preflight, artifact/recovery/runtime validation, native continuation, current
boot checks, an exclusive flushed request marker, one-time selection,
post-selection checks, sync and a delayed reboot. Unique selectors require
N, stage 5, explicit step 0, diagnostics off and pinning. Failure clears its
own pending entry while retaining the request marker. The reviewer did not
execute the queue.

At the final check, `saved_entry=spx-known-good`, GRUB `next_entry` was empty,
EFI `BootNext` was absent, and N had no request marker. Root must preserve
the final M snapshot and repeat immediate identity/pending-selection checks
before selecting N once. N requires its own observed and hashed result;
automatic recovery across an early hang remains unvalidated.

The checker is `/var/tmp/spx-review-n-preparation.py`. Its first execution
passed; the report and checker are preserved separately in
`/var/tmp/spx-n-preparation-review-20260922/` for the preparation archive.
