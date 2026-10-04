# Touch reopen audit and output bounds candidate, 2026-10-02

Checklist: I01 investigation, I02/I03 command-path correctness. AP remains the
running kernel on boot `7cc51af7-1dfb-4722-a23d-6e262a0e2c6f`; no new boot selected.

The AM/AO/AP final-result manifests were rehashed before comparing raw traces.
All eight recorded startup windows returned0 from reset assertion, regulator
enable and reset deassertion. AO's successful window2 began4.186ms after the
previous logged close, with19.978ms between reset assertion/deassertion records.
Failed window3 began417.911ms after its preceding close, with24.779ms between
reset records; it received no powered IRQ and no accepted reports. Clean AM/AP
reopens followed logged power-down by102.261/38.605ms. These software timestamps
do not support a simple minimum-off-time explanation for the failed sample.

The logger ends at ready, so close-time sleep-pinctrl and regulator-disable
results are absent. Caller identities and physical rail/reset states are absent.
AO's timeout cleanup has no close timestamp; window4's prior *logged* close is
not its actual last power-down. There is no evidence-based startup timing fix
from these samples. I01 remains open, as does the missing R01 shutdown console.

The source audit found a separate output-builder defect. Its content length
includes a two-byte length field and report ID, while the content pointer refers
only to payload. The candidate copies `content_length - 3` bytes and zeros all
remaining transmitted bytes after that payload. Previously the copy included
three extra bytes and zero-payload requests could retain old packet contents.
This affects feature/output commands, not AO's silence before its first reset
response and descriptor request. No causal startup claim is made.

The candidate also validates the minimum content length, requires a payload
pointer for nonempty content, uses wide arithmetic for size/alignment, and checks
both packet-buffer capacity and the output header's12-bit byte count. Caller
checks reject empty reports and oversized SET/output requests before indexing
the report ID or narrowing lengths. Device-advertised limits remain enforced.
For accepted sizes, the existing transfer length and header/body layout are
preserved; only payload bounds and trailing zero initialization change. The
legacy extra trailing bytes are retained pending a separate protocol review.

Only three C functions changed: `spi_hid_send_output_report`,
`spi_hid_ll_raw_request` and `spi_hid_ll_output_report`. Header/config, reset and
power/IRQ timing, startup retries, input response ownership, audio and DT are
unchanged. GET response ownership/length handling remains a separate review;
this output fix is not a complete input/command-path audit.

The native SPI-HID object compiled without warnings. Extracted candidate C
passed81,951 ASAN/UBSAN regression cases, covering payload lengths across the
buffer range, eight device maxima, exact wire bytes and zero trailing bytes,
empty/malformed metadata, high16-bit lengths, caller length narrowing, return
values, readiness and bus errors. SPI submission is mocked; no physical input
or live device reset/rebind was performed. Strict checkpatch reports no issues,
and reverse patch applicability confirms the delta against the working tree.

The first candidate's regression assertion exposed the12-bit header limit.
That candidate, harness and failure log are preserved in
`initial-header-limit-finding`; the final candidate rejects unrepresentable
lengths. The final regression also explicitly covers high16-bit arithmetic.
No old vulnerable implementation was executed as a reproduction test.

Evidence is archived under AP's `output-bounds-candidate-20261002`: before/after
source/diffs, unchanged config/header, old/new objects, candidate patch, build
logs, actual extracted-code regression sources/results and the reopen audit.
The running kernel and installed202-module AM tree remain unchanged. Known-good
recovery payloads/module tree/entry/EFI and default/empty selection are verified.

The live tracked source now differs from AP's frozen source provenance by this
reviewed C patch. AP's exact-source preboot guard must reject that difference;
do not bypass it or overwrite AP build evidence. The next deployment requires a
distinct-release full build, preserved source/config/modules/DTB/initramfs and
new attempt guards bound to this candidate. Hardware boot and real command/input
regression are still pending; no acceptance checkbox is closed by these tests.
