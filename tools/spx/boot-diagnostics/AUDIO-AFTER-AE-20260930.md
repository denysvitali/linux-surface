# Next silent boundary: native enumeration with WCD GPIO pin2

AE has a clean observed touch startup and repeats AC/AD's native left
0217:2110/unique3 attachment with the forced worker disabled. No startup policy
change follows from this single clean boot. Preserve the bounded touch logger
and return to the unresolved second-speaker enumeration question.

AF reuses AE's exact kernel,187 modules, private initramfs, config/source and
AB-identical DTB. Change only spx_attempt=20260930ae->20260930af and
wcd934x.spx_wsa_en_pin=1->2. The existing read-only MFD selector applies masked
DIR/VAL updates before adding GPIO/codec/SoundWire children. Raw two-pin
overrides remain-1, swap remainsN, native force/core/watchdog0 and exactwindowsN.
No DT identity, port map, controller policy or touch policy change is bundled.

The software GPIO expectation is DIR0x04/VAL0x1c, selector2, one pin2 log.
This is a falsifiable reset-state expectation, not a physical-voltage claim.
An update-return-ignoring log and cached nonvolatile views cannot prove pin
drive or which physical speaker is powered. See the correction in
AUDIO-CONTINUATION-20260930.md; the older SD_N report overstated its evidence.

Collect at620s, return at900s unless the full predeclared scope verifies. Keep
AE's strict functional baseline, topology and left-attachment criteria; change
only the expected GPIO selector/register view/log to pin2. A newly observed
2110/unique4 device without a matching DT node is a diagnostic finding and
fails that strict baseline. Do not change matching criteria after the result.
Preserve raw words/status, both read return codes, all decoded IDs, topology,
native errors, touch windows/state, IPTSD, graphics/Wi-Fi and runtime PM.

A separate diagnostic field records whether pin2 software state, native path,
bounded identity logging, DSP/controller and graphics/Wi-Fi/touch are valid,
with at least one paired rc0/0 decoded0217 identity (part2010 or2110,
unique3 or4). It does not control fallback or waive firmware/attachment
requirements. No trace means no positive enumeration diagnostic. Sameunique3,
unique4, no trace or a software-state mismatch are all useful distinct outcomes;
none alone proves physical routing or completion of the bridge reads.

No playback, capture, PCM probe, input-event read or live restart/rebind/reset.
Keep spx-known-good persistent default; verify boot ID, pending selection,
source/config and all recovery/payload/module/runtime hashes before one-shot
reboot. Archive source/config and all artifacts for this attempt. Automatic
EFI/early-kernel recovery remains unvalidated; experimental boots are explicitly
authorized including possible manual power cycles. Collect AF before choosing
another experiment; never blindly re-arm a failed image.
