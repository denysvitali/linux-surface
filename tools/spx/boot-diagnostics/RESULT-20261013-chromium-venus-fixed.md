boxes closed: 3 of 47; newly closed: none.

# Stock Chromium uses Venus for H264 decoding

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`; no reboot. Installed ArchARM Chromium
`152.0.7977.64-1` was used unchanged. Public Big Buck Bunny playback was muted.

**Changed:** native SQ2 Iris1 firmware requires HFI CODECCONFIG when H264
input is consumed without producing a picture, and rejects the flag with
slices. Venus now recognizes standalone Annex-B SEI/SPS/PPS/AUD/filler/SPS
extension in MMAP input, supplies that flag, and omits header-only input from
picture timestamp tracking. Picture-containing buffers keep their old flags.
The compatibility parameter defaults on; diagnostics default off.
Firmware evidence: `VIDEO.IR.1.2-00042-PROD-1`, input flag provenance at
`0x8dc24`, missing-config check `0x8d6a4`, slice rejection `0x8d6f0`, NAL
dispatch `0x964a0`; AUD/filler/SPS-extension consume through `0x96710`.

**Observed:** the identical split SPS/PPS/SEI fixture changed from zero to60
decoded frames. Stock Chromium's V4L2Stateful decoder then played 1920x1080
H264: video time advanced119.92 seconds over120.03 seconds, with3600 new
frames and33 new dropped frames. A captured public video frame was correct.
Closing and reopening Chromium succeeded. The GPU process held `/dev/video32`
while its log selected Venus CAPTURE NV12 1920x1088; software playback alone
is not the evidence. Ordinary launcher/platform selection and saved decoder
flag were verified on installed modules.

A further AUD delimiter regression was reproduced and fixed: the same public
stream, modified only by stream copy to insert AUD, changed from zero frames
and an input timeout to60 frames/124 input returns without timeout. Stock
Chromium played the AUD MP4 (794 frames at26.38 seconds, one dropped); a fresh
browser reopen decoded the complete30-second clip (900 frames, three dropped).
Both final browser exits returned0; no remaining video-node holders or kernel
timeout/refcount/fault messages occurred after the corrected module load.

**Installed:** matching core+decoder modules in the running release's module
tree, normal `modprobe` defaults, `~/.config/chromium-flags.conf` containing
`--enable-features=AcceleratedVideoDecoder`. Encoder remains outside the module
tree and blocked by `/etc/modprobe.d/spx-venus-decoder-only.conf`. The signed
`llvm22-libs` package restores the installed Mesa driver's LLVM22 dependency
after the stopped Chromium build's toolchain change. No browser or Mesa rebuild.
Private browser-build outputs are retained; test browser/server stopped,
locks released, boot default and recovery unchanged.

Evidence: `/var/tmp/spx-venus-sei-config-{sustained,reopen}-20261013.json`,
`/var/tmp/spx-venus-standard-launch-{playback,gpu}-20261013.json`,
`/var/tmp/spx-venus-aud-{before,fixed,browser,reopen-browser,fixed-kernel}-20261013.log`,
`/var/tmp/spx-venus-aud-{playback,reopen,gpu}-20261013.json`.

**Meaning/next:** the requested Chromium H264 hardware decode and reopen work
without recompiling Chromium. D03 stays open for the full format/path inventory,
other codecs and the parked encoder fault; those are not established here.
Human observations remain deferred until the end. No additional H264 trial
or browser build is needed for this correction.
