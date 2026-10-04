# W prepared: force-attached SoundWire write FIFO correction

V returned to known-good after the 900-second fallback. W is a distinct
`7.3.0-rc2-spx-mainline-20260927w+` kernel. The source change adds
`spx_forced_attached` to the existing SoundWire flush-and-settle write path,
which avoids rejecting codec writes solely because the bridge reports a stale
full write FIFO. The DTB is byte-identical to U's corrected 0x2010 DTB. W
retains V's boot-only `spx_enumerated_mode=1` and all other audio selectors.

The complete W build archive has 953 verified files and 272 symlinks;
`build-sha256.json` is
`3a68b16cea6e4c01a78ca99e47f013bccb2f80d7f738ccaaf5658236db5f2758`.
The installed module tree has 202 verified files. The independent artifact
review is
`2d58c9355771aef2433b0db977c21b4972d5747e82e813167e93a86290cd6ec9`.
The old R boot slot was copied into W's permanent archive and all three
payload hashes checked before freeing its boot-partition space. W's own
kernel, initramfs and DTB have SHA256
`25a386675b5429f00e78008eaa8c2ae8797046f34b09d250cc4468c7ac9104ab`,
`d79a804a8febd9599959c7c38bcedab65c4ca7188a0ea26514111ff980786fd7`
and `ee7f763c14a07b9f956ca65871a9a19851392b444bd754323db6df951fe6f81a`.

The known-good boot ID before selection is
`b9a390b7-fb58-40bc-8ae2-8404ee9e88d2`. W's installation review
rehashes those payloads, the three recovery files, eight runtime files,
complete build archive and installed modules. It also preserves a 134-file
known-good preboot snapshot, manifest
`83404630cd252fc7b85a34c524940a19562fe701c712248aeaccecb2d83dec77`.
The persistent GRUB default is `spx-known-good`, `next_entry` is empty, EFI
BootNext is absent, and W's 620-second collector and 900-second fallback are
enabled but inactive. No W boot is selected at this writing.

Use only the archived `queue-w-once.py`. It writes a request marker, selects
W for one boot, then schedules a separate guard that rechecks the boot ID,
pending entry and hashes immediately before reboot. The result collector
requires zero write-FIFO overflows, zero WSA status-update failures, logical
attachment, controller/card registration and the graphics/Wi-Fi/touch
baseline. It records later physical read underflows separately; a pass does
not establish working speaker playback.
