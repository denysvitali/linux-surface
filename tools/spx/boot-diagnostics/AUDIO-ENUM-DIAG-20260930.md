# AA: bounded identity provenance logging

Z's automatic fallback started at boot +900.092s, refreshed evidence at
+901.556s and returned to known-good boot
`e0479717-1fe0-4a8f-a6ac-af198c4b703a`, kernel `6.18.3-1-surface+`.
Its 480-file recovery archive manifest is
`581fc0686e13ab759501ce254c4d9f6b4b47ff1e9f201c8393c20a73fdf6299e`.
No new trial is selected.

`drivers/soundwire/qcom.c` now has default-off, read-only
`spx_enum_diag`. Each controller gets an atomic budget of eight existing
enumerator-table transactions, producing at most eight raw-word/status lines
and eight decoded-ID lines. It captures the return values of the two reads
already performed by `qcom_swrm_enumerate()` and logs raw words only when their
read succeeded. Decoded fields are logged only when both reads succeeded.
Logging performs no extra register read/write, reset, retry or assignment;
the preexisting matching and error paths remain unchanged. In particular,
the existing enumerator's handling of failed reads is not repaired here.

The native `drivers/soundwire/qcom.o` compile passed without warnings.
Source SHA256:
`1109a62060e06a052d9dcdc46257402706f4d194144bead74754c7948e181ea9`.
The first compile attempt stopped on root-owned generated-file permissions;
the successful retry used the same ownership as the earlier build. No module
was loaded, replaced or changed on the running known-good boot.

Build a distinct `7.3.0-rc2-spx-mainline-20260930aa+` payload with the same
kernel config except localversion, and verify the same DTB as Z. Its diagnostic
selector is `soundwire_qcom.spx_enum_diag=1`; retain Z's pin-1 selector, DT,
force attach and transport settings. Read and preserve the raw status snapshot
separately from forced logical attachment. A logged identity is not proof of a
physical attachment, stable addressing or acoustic output.

Archive the new kernel/modules/initramfs, source/config and logger before any
deployment. Keep known-good as the persistent default, select the trial once,
and collect before fallback. No playback or capture is authorized.
