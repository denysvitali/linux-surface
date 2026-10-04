# Independent O preparation review — 2026-09-22

**O's prepared state passed independent read-only review at N uptime
929.11–932.41 seconds.** The origin boot remained
`49e88055-f682-4317-9f81-41cc9cf51dbf`, release
`7.3.0-rc2-spx-mainline-20260922l+`. O had not been selected and has no
hardware result. The checker made no service, timer, device, parameter or
boot-selection changes.

[N's completed result](RESULT-20260922n.md) covers **616.08 seconds** without
a recovery return. The checker independently rehashed all **292 result
files**, verified exact manifest coverage and validated the immutable proof:

```
d56fc12297222aa12f182f292d03cdb9c0a3b7b722e615cfa062e8969018d092
```

O's global and per-attempt manifests agree and pin that proof with the
correct origin boot, release, attempt and result path. Prepared preflight
names the same validated origin. N completed stage-5 step-0 reads with zero
observed INT_STAT and INT_EN and retained the guarded baseline; it did not
establish interrupt acknowledgment or audio transport.

## Exact reuse and command line

All **937 copied build files** match N's unchanged L build manifest with
exact coverage, and all **272 symlinks** match N. All **202 installed
module-tree files**, including **187 modules**, match the copied manifest;
each module's vermagic names L. Build commit, current configuration and
archived source diff agree with the reused build. Only the explicitly
allowed README/component-status tracked documentation differs from L's
original snapshot. The build and extraction directories are private, and
the archived initramfs is mode 0600; this makes no 0600 claim for deployed
VFAT files.

All three installed payloads, three recovery files and eleven runtime files
match N's unchanged hashes. Payloads remain under `/boot/spx-trial-20260922l/`:

| Payload | SHA-256 |
| --- | --- |
| Kernel | `8d5703cb36ddbc0679a93e54d1159c2f6bea6acc06b3def119e323be0bbf6e85` |
| Initramfs | `9c09fcec33e5f5ac1b04d5f071354957ef1deba5468dffa73f4a0f938cc3c391` |
| DTB | `5adbda173a4c71e38d02764803da2aa031ec5ded2d6491a6fee6cc483f2235a5` |

There is no O payload slot, rebuild, module installation or slot retirement.
The ordered command line changes only `spx_attempt=20260922n` to
`spx_attempt=20260922o` and `slim_qcom_ngd_ctrl.spx_stage5_step=0` to `2`,
with no added or removed tokens. Every critical selector occurs once,
including unchanged stage 5, `spi_hid.startup_diag=0`, pin-after-QMI 1 and
the 600-second window. Regenerating the entry from the manifest reproduces
`entry.cfg` exactly. The custom configuration contains that single entry;
both GRUB configurations pass syntax checking. Main `grub.cfg` is unchanged
and retains `spx-known-good` as persistent default.

The unchanged NGD source blob is
`f7ca305ba9221bb43d08b39cf266bb2f4ba57e28`, SHA-256
`ac5977296b408d6096b67675f4e1ff1b1267a796bb3d57e55abf33cddb1a392b`.
The verified NGD module SHA-256 is
`31df6e27e5f8058dd9ff33bf2320cd38dc5e5a6ea4049771b72179210b380f1d`.
The current and archived [step-2 source review](AUDIO-STAGE5-STEP2-20260922.md)
both match SHA-256
`036078ef92b3de0992a16ae319fd90a91bc403b8c022d41d8e503d0126cea6e2`.

That review applies to these exact prepared artifacts: the successful
synchronous stage-5 step-2 path performs nine 32-bit MMIO reads and one
INT_CLR write, after the firmware-changing QMI request. The write operand
is a separate unlogged INT_STAT read; the preceding printed value cannot
establish the actual mask. The final read observes INT_STAT, not INT_CLR.
The disabled allow flags do not prevent this selected case's write.
Step 1 is not cumulative with step 2, and step 3/nonzero INT_EN remains
excluded. Preparation does not validate any of these accesses on hardware.

## Origin state and one-shot boundary

Live N still has diagnostic parameter N, mode 0444, audio stage 5, all
substeps zero, pin Y/refcount 1 and all DMA, INT_EN, full-controller, PIO,
window-dump, PDR, bypass and PIO-debug guards N. Selection, response-type,
base-offset, DMA-mask and poll-RX values match the reviewed baseline. The
child is runtime-suspended with active time 0 and control auto. Prepared
step 2 has not changed the running step-0 module.

The early logger, return timers and evidence service are enabled; periodic
evidence collection is active. Origin return timers are inactive. A native
Happy query validated the existing session/thread, automatic continuation
message, workspace and host process arguments without printing or retaining
raw metadata. The copied N continuation acknowledgment matches its source.

The archived preparation helper SHA-256 is
`115fb21d2c32483c9efde8265b15993f920280f417311fa01d63e7ba49da265a`;
generated queue SHA-256 is
`8f2d622746d22cd7ed3aa04d22ae191bc488062ea65adbc238c2442cf328f057`.
Both equal the separately reviewed versions. The queue compiles and retains
preflight, artifact/recovery/runtime validation, native continuation, current
boot checks, an exclusive flushed request marker, one-time selection,
post-selection checks, sync and a delayed reboot. Unique selectors require
O, stage 5, explicit step 2, diagnostics off and pinning. Failure clears its
own pending entry while retaining the request marker. This review did not
execute the queue.

At the final check, `saved_entry=spx-known-good`, GRUB `next_entry` was empty,
EFI `BootNext` was absent, and O had no request marker. Root must preserve
the final N snapshot and repeat immediate identity/pending-selection checks
before selecting O once. O requires its own observed and hashed result;
automatic recovery across an early hang remains unvalidated.

The checker is `/var/tmp/spx-review-o-preparation.py`. Its first execution
passed. The checker and report are preserved separately in
`/var/tmp/spx-o-preparation-review-20260922/`; the report SHA-256 is:

```
6bc88dc04795e2653f7cbceb3e6d0ca8ec924c42b22c4268a886f44aa6e1e6ac
```
