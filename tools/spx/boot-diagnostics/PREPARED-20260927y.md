# Y prepared: shadow-backed WSA Smart Boost control read

X boot `f5039e57-1a71-4833-9193-6da333d4d4f9` passed its automatic
attached-only silent PCM baseline. Y is a distinct
`7.3.0-rc2-spx-mainline-20260927y+` kernel that changes the WSA
`Smart Boost Level` enum to use the existing register shadow for control
reads and writes. It refuses writes to an unattached slave. The other X
audio selectors and corrected DTB are retained.

The Y build archive has 977 verified regular files and 272 symlinks;
manifest SHA256 is
`2798579c0b4b5d54365c4da9514470ad6955d75e5cb6329268f66046e33188ea`.
The independent artifact review SHA256 is
`2591c1dca6252edb0004ed53e3b99adc5954841c2c173e541c9884cf248a94d5`.
There are 187 Y modules and 202 installed module tree files. The compressed
kernel, initramfs, DTB, config, and source diff hashes are respectively
`62880bed921abd838e1829f995dc25e41ba74144dadd653a0767575c38f65533`,
`b194b9a7a4e60e19be7fdeb9ed260619bf945439c1a57899ffd115170f16e09d`,
`ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a`,
`2265cf525d5019c52979abe6717772c560342ab44e61e4a796786369f2a96b13`,
and `aae1ad9857ecb0cb2a0dd86ba6ee66ffc79658382d990073270461cdd0c8674a`.
The X boot slot was preserved and hash-checked in Y's permanent archive
before removal from `/boot`.

The independent installed review SHA256 is
`689655f94f75b0fbd12487d90cc175feb1275cc5a131bb09da50dbc3ffb6df22`.
It rehashed the three recovery files, all Y payload/runtime files, the
complete build, 202 installed module files, and a 324-file X preboot
snapshot. GRUB still saves `spx-known-good` as the persistent default,
`next_entry` is empty, and EFI BootNext is absent. The Y 620-second result
collector and 900-second fallback are enabled but inactive on X. No Y boot
is selected at this writing.

Use only the archived `queue-y-once.py`. Its immediate reboot guard rechecks
the boot ID, pending entry, module tree, payloads and recovery hashes before
reboot. On Y, run `y-mixer-read.py` and `y-silent-pcm.py` once each between
120 and 500 seconds. The mixer test queries both Smart Boost controls and
archives the kernel delta; the silent test repeats X's attached-only DAC
transport probe. The collector stops fallback only if both bounded tests
pass without new SoundWire underflows and the graphics/Wi-Fi/touch baseline
is healthy. Its result also reports the full-boot read-underflow count. A
pass does not establish audible speaker output.

The first queue helper invocation stopped before creating a reboot-request
marker or selecting GRUB because it checked X's long-return exclusion path
for Y's marker. The Y queue path and the Y silent-test fallback-timer name
were corrected in the archived deployment sources. All eight source scripts
were rehashed; corrected manifest SHA256 is
`48af4cd90679816e979abf5c7fd302ab409568e2346872f66a343c600faa31d4`.
The separate correction review SHA256 is
`fc7911346948f975c46f5405cdfd87f363dd871441fa23740fd461c11e32beaf`.
The installed payload, recovery, and runtime hashes remain exact. No boot
selection or reboot occurred in the rejected invocation.
