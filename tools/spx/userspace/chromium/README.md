# Chromium hardware decoding on Venus

2026-10-13: installed Chromium152 now decodes H2641080p with a Venus-side
correction, without rebuilding Chromium. Native SQ2 firmware requires
CODECCONFIG for header-only SPS/PPS/SEI/AUD/filler/SPS-extension input;
it rejects that flag with slices.
The driver recognizes those standalone buffers and keeps whole pictures
unflagged. The identical split fixture returns60 frames; installed Chromium
counts3600 frames over120 seconds (33 dropped) and reopens successfully.
An AUD-containing split fixture also returns60 frames after the correction,
versus zero before it. Normal driver defaults, installed modules and the
persistent Chromium decoder gate are verified. The encoder remains blocked;
D03 remains open for full codec coverage. See
`tools/spx/boot-diagnostics/RESULT-20261013-chromium-venus-fixed.md`.
The next ordinary Chromium launch reads `~/.config/chromium-flags.conf` with
`--enable-features=AcceleratedVideoDecoder`; existing browser processes must
exit before relaunching to pick up the flag.
The browser patches below are retained as a stopped, unvalidated fallback.

Applies to Chromium152.0.7977.64, revision
506c834ecceaa943c5f41e6cfe7f68acb5c45346.

Venus advertises H264/DYN_RESOLUTION, not CONTINUOUS_BYTESTREAM. The V4L2
contract expects one access unit per OUTPUT buffer. Chromium's current
reassembler emits standalone SPS/PPS/SEI buffers. This candidate retains
those prefixes with the next picture and preserves picture lookahead.

The patched decoder/test objects compile, but parser execution and a linked
patched browser remain unvalidated. A 2026-10-13
hardware comparison using v4l2-ctl and identical H.264 bytes produced 60
decoded frames with whole access units, zero with split SPS/PPS/SEI buffers,
then 60 again with whole units. The split case reproduced the late
SOURCE_CHANGE/FLUSH timeout. This supports the framing diagnosis; it does
not establish browser playback or validate this patch. See
`tools/spx/boot-diagnostics/RESULT-20261013-venus-framing.md`.

Applies to all stateful H264 drivers and needs
parser/EOS/fragmentation and driver regression tests. Also changes malformed
slice/no-NAL handling to fail; that stricter behavior needs review in the
Chromium build environment. No firmware flags or hardware constants changed.

Build using the Arch Linux ARM Chromium152 package recipe with native V4L2,
applying this patch after source preparation. The private native fallback
build is stopped in `/var/tmp/spx-chromium-build`: exact152 source/recipe,
signed native clang23/GN/Rust/Node tools, `use_thin_lto=false`, `symbol_level=0`.
Its last build used six jobs; incremental outputs are retained.
Obsolete clean worktree cleanup made local storage available; output/link
resource needs remain unmeasured. Build log:
`/var/tmp/spx-chromium-build-20261013.log`. Do not install this candidate or
claim playback works until compilation, parser tests and real hardware browser
playback/reopen succeed. The fallback has not been installed.

Retained source/report: /var/tmp/spx-chromium-au-fixed-20261012.{cc,md}.
Current result: tools/spx/boot-diagnostics/RESULT-20261012-chromium-venus-events.md.
Reboots were authorized again on 2026-10-13; follow current `AGENTS.md` trial
rules. Fault-producing encoder tests remain parked. Human checks are deferred
until the end by the user.

Apply `0002-h264-reassembler-regression-tests-WIP.patch` after `0001`.
It exposes the existing reassembler declaration in a header and adds eight
GoogleTests using actual H264Parser/DecoderBuffer and software-generated
multi-slice fixtures. It does not change decoder behavior. Tests assume
whole-NAL input chunks, matching the existing contract. Decoder and parser-test
objects compiled; test execution and the full browser link are pending:

```
ninja -j2 -C out/Release media_unittests
out/Release/media_unittests --gtest_filter=H264FrameReassemblerTest.*
```

The browser build was paused to build this target first in the same output
tree. Test-build log: `/var/tmp/spx-chromium-parser-build-20261013.log`.
The lite archive's missing test-font bundle was fetched from the exact `DEPS`
object and verified. When resuming/regenerating the system-toolchain build,
keep `CC=clang CXX=clang++ AR=ar NM=nm RUSTC_BOOTSTRAP=1` exported: unbundle
GN reads those environment variables. An invocation without them failed before
test compilation; the corrected native build is stopped.

## Reproducible Arch Linux ARM package (WIP)

`0003-archarm152-package-AU-WIP.patch` targets the original recipe snapshot
`66a990e2a4036d89ae4240f97fc3364e1072449e` in Arch Linux ARM's `PKGBUILDs`
repository, `extra/chromium/PKGBUILD`. Use that snapshot's package directory,
not current master. From a clean recipe directory, with `SPX_CHROMIUM` set to
this directory's absolute path:

```sh
cp "$SPX_CHROMIUM/0001-h264-stateful-access-unit-reassembly-WIP.patch" .
cp "$SPX_CHROMIUM/0002-h264-reassembler-regression-tests-WIP.patch" .
patch --fuzz=0 -p1 < "$SPX_CHROMIUM/0003-archarm152-package-AU-WIP.patch"
makepkg
```

Do not use `--nocheck` or install the result before hardware playback/reopen
passes. `prepare()` applies both patches after the distro preparation.
The recipe verifies the patches and exact Chromium152 DEPS font archive;
`check()` builds `media_unittests` and runs `H264FrameReassemblerTest.*`
with the native compiler environment and one test-launcher job. Full distro
outputs remain: browser, sandbox, chromedriver, launcher and resources.

Local constants: `arch=aarch64`, `pkgrel=2` distinguish the candidate;
Ninja/MAKEFLAGS use four jobs rather than the recipe's sixteen;
`use_thin_lto=false` limits local link memory. `symbol_level=0` is retained.
The font object, generation and SHA256 come from exact152 `DEPS`, not a newer
release. Native tools/dependencies must match the recipe; local full-link
memory/disk fit is not yet established. Only patch application and shell
syntax were checked for this integration, not a complete package build.
Installed Chromium and persistent flags are unchanged.
