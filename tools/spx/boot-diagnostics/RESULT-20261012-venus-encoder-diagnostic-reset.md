boxes closed: 3 of 47; newly closed: none.

# Encoder diagnostic interrupted by another reset

Trial boot e61d4de7-37ae-4432-b5f9-079399782874,
kernel7.3.0-rc2-spx-mainline-20261004bg+, candidate dcb395476b20.
User explicitly requested live run. Matched core/dec/enc loaded with scoped
child-autoload barrier; no overlapping decode, sound or capture workload.
One120-frame640x360NV12 H264 encoder command launched20:27:42 with30s timeout
and5s kill grace; separate bounded journal follow started at same time.

User returned after device reboot. Current boot
6272005e-0a08-41e9-b9b6-2166ff0a04f1, unchanged7.x baseline; desktop manager
active, previous test processes absent, locks free. Encoder output file0bytes.
Live capture file empty. Previous persistent journal ends20:27:42 at launch,
with no encoder bufreq/allocation/ETB/FTB lines, SFR or final panic. Pstore empty.
No coordinator reboot requested for this run. User reports it likely restarted
by itself; they did not report a manual power cycle. Treat automatic reset as
likely, not proved. Reset cause remains unknown; no final fault trace survived.
Do not attribute reset to the diagnostic code.

No encode pass, no buffer-address/protected-PERSIST inference, no recovery fix.
Prior native H264 baseline/high120-hash decode success remains valid for its
recorded prior boot; this failed encode is not a decoder acceptance trial.
Installed modules unchanged; baseline/recovery payload hash check passed,
boot selection empty. Temporary autoload policy removed; locks free.
No hardware constants changed; only opt-in diagnostic line/first-frame limits.

Logs /var/tmp/spx-venus-encode-buffers-postreset.log. Stop fault-producing encode
trials: useful evidence was lost again and recoverability is unresolved.
Next requires reliable pre-reset capture/recovery information and authoritative
protected-memory ownership/context contract; no speculative secure mapping.
