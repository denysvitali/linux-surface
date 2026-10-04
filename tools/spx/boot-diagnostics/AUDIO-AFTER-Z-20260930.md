# Next silent boundary after Z: enumeration identity provenance

Z's GPIO software-state and baseline checks passed, but its scoped topology
failed because a third `0217:2110`/unique-3 device appeared without a firmware
node. Read RESULT-20260930z.md and collect the scheduled recovery outcome
before another boot. No sound run is authorized.

The source supports two creation paths for a device with no firmware node.
`qcom_swrm_enumerate()` decodes the controller's two enumerator-table words and
creates an unmatched ID with `sdw_slave_add(..., NULL)`. The generic SoundWire
core can also create an unmatched device after a device-0 ID read, although
that path logs `Slave Entry not found`, which is absent from Z's kernel log.
The Qualcomm table path is therefore the leading inference, not a captured
call trace. SoundWire's bus probe explicitly refuses devices with no firmware
node, explaining why the extra device has no codec driver.

The force-attach path independently synthesizes an attached status for logical
device 1 and selects only DT parts 0x2010. The hardware table and synthesized
attachment must not be conflated. Z does not justify changing the DT back to
0x2110, suppressing the new device, enabling pin 2, assigning another address,
or changing DP1 to DP4. A single table observation can be stale or mixed.

The next diagnostic should log a bounded number of **existing** enumeration
transactions: table-read return codes, raw words, decoded manufacturer/product/
unique ID, the raw status snapshot, the status used by enumeration and whether
force attachment is active. It must default off, perform no extra bus read,
retry, reset, assignment or GPIO write, and leave current matching decisions
unchanged. Use a distinct built kernel and exact Z GPIO/DT/transport selectors
for its one-shot trial. Archive the unmatched device rather than treating its
presence as a successful physical attachment. Capture initial and later state
before judging whether 0x2110 is repeatable and associated with real presence.

A later acoustic test still needs an explicitly requested bounded playback
run and a contemporaneous microphone floor. A clean log or software output
state alone does not prove a physical speaker path.
