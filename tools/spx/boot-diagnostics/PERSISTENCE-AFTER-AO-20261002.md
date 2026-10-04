# Next diagnostic after the verified AO result

AO passed its scoped baseline but did not preserve the outgoing shutdown console.
Before attributing touch behavior to the new shutdown callback, diagnose this
missing evidence. The next proposed trial (AP) should reuse AO/AM's exact kernel,
modules, DTB, private initramfs, source/config and pin2/native selectors, adding
only `ramoops.dyndbg=+p` besides the new attempt marker. This is a reviewed design;
AP has not been prepared, installed or selected.

The local source and live debug catalog establish that this can use the existing
kernel. CONFIG_DYNAMIC_DEBUG=y; fs/pstore/Makefile builds ram.o and ram_core.o
into ramoops. Five currently disabled sites belong to that module. Dynamic debug
processes boot selectors at early_initcall, before ramoops's postcore_initcall.
Documentation/admin-guide/dynamic-debug-howto.rst describes the module.dyndbg
selector for built-in modules. No rebuild, memory-map change, panic or live
rebind is needed to enable these existing messages on a future boot.

The useful sites in persistent_ram_post_init distinguish an existing empty
buffer, a valid nonempty buffer, and a signature mismatch before initializing
it. persistent_ram_new then logs the zone label/address/size. Preserve their raw
order so the old-buffer finding can be associated with the console zone rather
than a dmesg zone. The diagnostic does not print the old log contents. Its small
set of probe-time messages introduces a timing change that must be acknowledged.

Retain the strict 620-second baseline and900-second fallback unchanged. Diagnose
persistence separately: a signature mismatch is evidence that the expected
buffer signature did not survive to ramoops probe, not proof that firmware was
the writer. Empty/invalid data does not demonstrate callback failure. A valid
retained console only establishes callback software completion if it contains
the exact outgoing AO boot identity followed by begin and complete markers.
Software completion does not establish physical rail-off.

The AO persistence archive (13files, manifest
94d5e89b8a2b85ae7203c59983e7d7077d21c8536905b2f8df931a82dd5b0627)
contains both boots' backend logs, the disabled debug catalog, source/config and
empty stores. The reserved-memory overlap warning concerns96e00000/98715000,
not the ramoops9a480000 reservation. systemd-pstore is inactive; existing
collectors copy records rather than deleting them. The exact point where
retention failed is still unknown.

Preparation must freeze AO result/review/source and outgoing pstore baseline,
verify the fresh boot ID, recovery hashes and empty selection, and use a new
exclusive request. Keep spx-known-good as default and never reuse AN/AO request
markers. Verify the whole new preboot guard under systemd, including its Git
source check. Validate all freeze input filenames before writing, and require a
complete verified prequeue manifest before selecting the boot: the AO filename
correction showed why queueing must depend on successful archival completion.

After the actual next boot, collect the old-buffer diagnostics and identity-bound
late console early, then the actual620s result before another experiment. If it
fails, leave900s fallback armed, verify the actual known-good return and preserve
evidence. No live display unbind/rebind or manual input/audio/PCM/reset testing.
