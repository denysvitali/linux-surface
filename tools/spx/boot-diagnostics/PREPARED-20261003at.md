# AT rear privacy provider trial

Read current boot ID/cmdline and attempt.json before acting. Outgoing AS UUID is
`29748fff-2312-42c5-982e-04bbd2304b52`, with passing combined baseline/rear idle
result. AT deliberately reuses AR release `7.3.0-rc2-spx-mainline-20261003ar+`;
uname cannot distinguish these trials. Never repeat an exclusive reboot marker.

AT is installed with no boot selected at this record's creation. Its independent
review streamed96,798 full source records, verified908 build files/272 links,
193 module vermagics/208 shared module files and54 embedded modules. Kernel,
config/source/module/initramfs content remains exactly the AR build used by AS.
Known-good persistent default, empty next_entry and absent EFIBootNext verify.
The four AT timers are enabled/inactive on AS. Automatic recovery across early
EFI/kernel handoff remains unvalidated under the existing boot authorization.

The new DT adds two rear privacy LED nodes and two sensor consumer properties
only. GPIO11 is active high/default off, from pinned vendor PRLD and SQ2 resource
evidence. Existing V4L2 code owns the LED through normal sensor registration.
FrontGPIO25 remains unclaimed; no receiver, analog rail or capture is added.
All existing AS properties/phandles/reservations match. Four focused schemas
and five negative relation/schema cases pass. Full board/upstream binding and
physical privacy/stream failure behavior remain open.

- Source archive: `488d6705fbdea620d59cdd67f73c63df5dcf9256a384e7a49cea1c421bf358f2`.
- Build manifest: `7e23c627c4b02ee44c0af9d8cc4e693133f510bebd49415d9f0e9b486c1d6df8`.
- Config: `0d315eff642a357d537b614ffd943955cd1700905a0ecf9b191401740a302fb1`.
- Kernel: `408515f77e82eac5803ccf7a6162d1c5a80d20deb1e1688afa3edc534f0fbe0e`.
- Initramfs: `ac00b9013eec27e6fda99fb125d506451993c81a2a68d56a9c1c2d6b6289065d`.
- DTB: `50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c`.
- 24-helper deployment manifest: `8728ab5259ea6b4314fc6bb8766815ce5ef6113ad4e215ad148036454338fa86`.
- 243-file outgoing snapshot: `ae7c1bd16606125ce560f86ec087e7b8779a9a19c59af2c0b6a578481ad2cfc9`.
- 55-file supplemental helper/source archive: `28364226d73c42d876cd8d3dd8e47c5ac5c8a9881951d536aa9cddb6968a2461`.

Offline policy preserves all12 strict baseline expressions and rejects39 initial
and39 final camera failures, including18 LED cases; six phase/timing failures,
stale identity and four baseline/camera truth combinations verify. Real state
guard2/12 and complete freeze1/17 cases verify. Initial filename generation
aborted before copying any helper because its exclusive assertion caught an
unchanged filename; failure retained, corrected mapping preserves all23 originals.
The result reviewer uses the corrected explicit-reuse `build_links_verified` key.

At60s collect providers,120s initial rear/LED state and620s a fresh final rear/LED
snapshot alongside unchanged baseline. Require normal rear/provider binding,
runtime suspend, three disabled zero-use rails,21 exact PMIC controls, one proper
GPIO LED off/max1/no-trigger, exact consumer relation, GPIO11 output-low/function0,
front25 unclaimed and no camera/LED errors. Collectors make no LED/GPIO writes,
streams, controls, reset/rebind or PCM operations. At900s fallback remains armed
unless baseline and both ordered observations pass. Software LED state does not
prove physical light, privacy timing, stream cleanup or complete camera function.

The full preboot guard passed under systemd without SUDO_UID in21.271s, bound
to the actual outgoing AS identity; all recovery, payload/module/source and
empty selection checks passed. Before selection verify native continuation,
freeze all records and queue only with queue-at-once.py. Read the subsequent
exclusive queue and immediate-guard records for actual scheduling.

Subsequent native continuation verification and26-file prequeue freeze pass;
manifest `2df3c6544beb14311262cc6ea2428efb60d6fef7590f7f92f4a60a42f041ec98`.
AT was selected once from actual outgoing AS, with known-good persistent default
and active30s immediate-guard timer. Inspect live boot/pending selection and
the guard proof before any further action; this scheduling is not an incoming result.

On continuation:

1. Verify new actual UUID, exact AT BOOT_IMAGE/spx_attempt, consumed selection and
   immediate-guard proof; keep known-good default.
2. Preserve transition with review-at-handoff.py and actual startup chronology
   with snapshot-at-startup.py before finalization, without live device operations.
3. Rehash/recompute60s provider and120s camera/LED results with normal reviewers.
4. After620s review-at-result.py, review-at-touch.py and camera-control reviewer
   with `--final`; preserve all regressions and the actual combined outcome.
5. Preserve failure/900s return before another experiment; never blindly re-arm.
   Stream timing, physical LED behavior and receiver supply/SID integration still
   need separate work. All47 hardware acceptance checks remain open.
