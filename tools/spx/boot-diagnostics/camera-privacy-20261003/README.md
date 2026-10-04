# Camera privacy contract and rear-only DT candidate

C05 work after AS boot `29748fff-2312-42c5-982e-04bbd2304b52` passed its
combined scoped baseline and normal rear identification checks. No camera
capture, GPIO write, vendor binary execution or new boot has occurred here.

The retained SQ2 DSDT and four vendor binaries are pinned by `decode.py`.
Complete bounded ARM64 disassembly of the platform PRLD parser and dispatcher
establishes the tuple layout: bits0–7 select sensors, bits8–9 select operation
kind, and GPIO kind1 uses bits10–12 for the CAMP GPIO resource index and bit13
for inversion. The dispatcher passes the requested Boolean unchanged when the
inversion bit is clear. Its sensor-ID constants match unique first DWORDs in
the retained rear, front and IR sensor GUID data; its explicit branches select
rear index0, front index1 and IR index2.

| Entry | Sensor | Resource index | TLMM GPIO | Polarity |
| --- | --- | --- | --- | --- |
| `0x0101` | Rear | 0 | 11 | Active high |
| `0x0502` | Front | 1 | 25 | Active high |

The other four entries are inactive. IR selects no LED entry in this PRLD table;
this does not establish that IR illumination is absent or validate its safety.
This resolves the software mapping left open by the earlier
[vendor inventory](../camera-capture-audit-20261003/VENDOR-POWER.md). Physical
wiring, visible operation and stream/idle/failure behavior still need tests.
The11-file decoder output manifest is
`47ca25245bd62901f7a8b2cdd91a84d7ff2ab84b33a88cc9d31d092f5c4648c3`.

`spx-rear-privacy.dtsi` connects only the rear sensor to a normal `gpio-leds`
provider on GPIO11, active high and initially off. Existing AR/AS kernel config
already enables LED class/GPIO support. The sensor's normal async registration
obtains `leds` with `led-names = "privacy"`; V4L2 disables LED sysfs control,
removes triggers and controls brightness with streaming. No custom LED driver,
front GPIO25 claim, guessed color, analog rail or CSI receiver is added.

`check_dt.py` compiles against the archived AS preprocessed source and verifies
exactly two new nodes and two new sensor properties. Every existing property,
phandle and memory reservation stays exact. Four focused schema selections pass;
three wrong GPIO/polarity/name relations and two malformed schema fixtures reject.
This is focused validation; the base board's existing binding diagnostics remain.
The offline candidate is
`50984a306a7cdac1f48083ce4257b4fed19384698a3afa33b6a4ac2303f53a8c`,
with36-file output manifest
`f21660a4912fc851c47408c9b11107300906fabb19238b1f0c09166a81e08c40`.
It has not been installed. The first validator used a `gpio-leds` selector that
did not match `leds-gpio.yaml`; the missing-GPIO negative caught this. Its complete
partial output and source are preserved, manifest
`136b37f534602224bb5ae86a8a1d6af87b5aff17552cdcc1abb587a551ca82c1`.
The corrected selector validates the provider and rejects the negative fixture.

At candidate preparation, the V4L2 `call_s_stream` wrapper lit the indicator after successful
driver stream start, and forces a failed stop return to success before turning
it off. Actual timing and failure cleanup therefore require explicit functional
review; framework availability is not a privacy guarantee. Current rear sensor
has no receiver/capture graph. C01–C05 and all47 acceptance checks stay open.

Subsequent offline work fixes managed rear stream-failure cleanup and V4L2
LED-before-start ordering. Read [stream failure cleanup](../camera-power-20261003/STREAM-FAILURE.md)
and [privacy ordering](STREAM-ORDERING.md) for tests, provenance and limits.
The actual AT trial installed this DT candidate and verified idle provider state;
the source changes have not been installed or functionally accepted.

Reproduce offline with system Python/Capstone/libfdt and fresh directories:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-privacy-20261003/decode.py /var/tmp/spx-privacy-decode-new
sudo /usr/bin/python3 tools/spx/boot-diagnostics/camera-privacy-20261003/check_dt.py /var/tmp/spx-privacy-dt-new
```
