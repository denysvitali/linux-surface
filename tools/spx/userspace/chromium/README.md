# Chromium H.264 access-unit reassembly candidate (WIP)

Applies to Chromium152.0.7977.64, revision
506c834ecceaa943c5f41e6cfe7f68acb5c45346.

Venus advertises H264/DYN_RESOLUTION, not CONTINUOUS_BYTESTREAM. The V4L2
contract expects one access unit per OUTPUT buffer. Chromium's current
reassembler emits standalone SPS/PPS/SEI buffers. This candidate retains
those prefixes with the next picture and preserves picture lookahead.

Uncompiled and unvalidated. The framing mismatch is a lead, not a proved
cause of SPX playback failure. Applies to all stateful H264 drivers and needs
parser/EOS/fragmentation and driver regression tests. Also changes malformed
slice/no-NAL handling to fail; that stricter behavior needs review in the
Chromium build environment. No firmware flags or hardware constants changed.

Build using the Arch Linux ARM Chromium package recipe with native V4L2,
applying this patch after source preparation. No full browser source/toolchain
or sufficient build storage is available on this device. Do not install this
candidate or claim playback works until a real browser build/test succeeds.

Retained source/report: /var/tmp/spx-chromium-au-fixed-20261012.{cc,md}.
Current result: tools/spx/boot-diagnostics/RESULT-20261012-chromium-venus-events.md.
No reboot commands or encoder tests are authorized.
