# SPI-HID output ownership and reboot quiesce candidate, 2026-10-01

AL's failed initial touch startup remains unresolved. This candidate finishes the
lifecycle groundwork from TOUCH-WORKER-RECOVERY-20261001.md; it does not add a
bootstrap retry or change reset timings, IRQ policy, wire format or audio policy.

The new output_lock serializes synchronous SPI writes with power-up/down. Output
rejects stopping/unpowered devices with ESHUTDOWN before submitting SPI or changing
bus error counters. Power-down first acquires this mutex, then closes the powered
input gate and drains startup/input before disabling the regulator. Power-up holds
the same mutex across enable and publication, preventing a late enabled rail after
power-down. Reset descriptor preparation now owns the existing request mutex,
matching normal output callers and preventing shared packet overwrite during DMA.
Order: request mutex -> output mutex -> input spinlock. Startup/input completion
paths do not acquire the output mutex; no input spinlock is held while acquiring
it. This is a local driver review, not exhaustive kernel concurrency proof.

Regulator failure behavior is retained: ordinary power-down restores powered on
failure, while permanent stopping rejects output regardless. Failed regulator
rollback does not establish physical rail state. The inherited sync_request
response ownership while it releases the request mutex is a separate issue.

A genuine SPI driver shutdown callback invokes the existing reviewed teardown,
with two fixed messages: SPX: shutdown quiesce begin/complete. The helper gates new
work, drains output/input/publishers/recovery and destroys HID before freeing IRQ.
The completion message only establishes helper return; it does not establish
successful regulator disable. No live shutdown/reset/rebind was invoked.

Offline ASAN/UBSAN verification: 60 output cases,24 unchanged power cases and
controlled write/power-down, power-up/power-down, shared-packet, input drain and
failed-power-off interleavings. Old ordering witnesses reproduced. Callback tests:
144 actual extracted stop/abort/shutdown/SPI-core dispatch cases and2 missing
callback/driver cases. Native object compile and strict patch style pass without
warnings. Workqueues, HID and regulators are mocked; no hardware claim follows.

Final driver74ae8e4d3d586fa7112622f4d85a800e83509b4cb876231b0afc79dc9ebc49b7,
headerd0afbddbe7498df062c4720273475ac3dc0026066bc5138eb39f69b057ec98be,
full tracked diff2b04f21658fc378163a054f2c17465f24595ecb8236987a224ca61899fa25af7.
Before distinct-release build, config remains AK50118c6b...; qcom SoundWire33aeace2...
and WSAe30ce5e4... unchanged. Known-good boot5384a3dd-8e3a-4683-bf6b-cdac9dc6b1c5,
6.18.3-1-surface+ remains active, default known-good, next_entry empty, no BootNext.

Frozen under AL: output-power-lock-candidate-20261001 (18 files,2258a074...),
reboot-quiesce-candidate-20261001 (18 files,0340ada7...). Independent review and
future full build preserve those original source/config/object archives.
Read AM-PLAN-20261001.md before deployment or a hardware handoff experiment.
