boxes closed: 3 of 47; newly closed: none.

# Venus native HFI decode works

Boot6c15131e-36e5-415a-af0c-22d8a46122b2,
kernel7.3.0-rc2-spx-mainline-20261004bg+. Candidateb7076dde3766
removes SC8180X hfi_video_arch2 override, uses established HFI_VIDEO_ARCH_OX1.
Mode2 SYS_INIT+8 selects Windows DXVA; native Linux211xxx query hits its
unsupported-command fatal. Mode1 selects native HFI; no opcode/SID/sizing
changes. Firmware proof /var/tmp/spx-venus-assertion.md.

Matched three-module stack rebuilt and loaded with scoped autoload barrier.
H264 baseline fixture: FFmpeg hardware decoder/dev/video32 decoded120 frames,
zero decode errors, exit0. Default FFmpeg output timing dropped119 due raw
fixture timestamps, so second decode uses fps_mode passthrough. All120 output
frame sizes+MD5 exactly match software decoder output (zero mismatches).
First run0.67s; all-frame hardware0.61s. No firmware fatal/query timeout.
Second run also verifies session reopen, not only first-stream success.

Candidates unloaded; post-trial journal no OF/refcount error, host warning,
Internal error or reboot. Boot ID unchanged. Autoload policy removed, installed
modules unchanged, lock released. No camera/mic capture/sound/display reload.
Logs /var/tmp/spx-venus-native-hfi-{kernel,decode}.log and
/var/tmp/spx-venus-{native-hfi,software}-all-20261012.framemd5.

H264 decode is now functionally verified. D03 remains open: enumerate supported
formats/encode blocks, test those paths/output and sustained real-media playback.
Next: high-profile B-frame fixture, bounded hardware encode from existing film
raw frames, sustained1080p real-media decode; then matched-stack installation.
