# Disabled rear-only control path draft

Target C01. This draft prepares a later normal-driver sensor-identification
experiment. It is not included in AR's boot DTB and has never been deployed.
CCI and the rear sensor remain disabled. No CAMSS, front camera, IR sensor,
placeholder supply or guessed analog rail is added.

The rear sensor uses CCI0 bus0/address0x10, MCLK0 at19.2MHz on GPIO13 and
active-low reset GPIO22. Its supply references resolve to the measured direct
SPMI providers: DOVDD→L14 (1.8V), AVDD→L17 (2.856V actual code), DVDD→L1 (1.2V).
The normal driver's ordered rail enable and fault-aware cleanup are required;
no direct register writer or separate fixed regulator substitutes for them.
CCI uses the reviewed SC8180X/fallback compatible pair, five CAMCC clocks,
existing TITAN_TOP_GDSC, register window0xac4a000 and SPI460.

After AR's actual620.97s passing baseline, the live draft now assigns only
CCI0's source clock to37.5MHz. The normal CCI driver enables clocks without
setting their rate, so the previous v6 draft inherited its boot-time rate.
SC8180X CAMCC explicitly supports37.5MHz and the CCI binding's v2 example uses
that rate. This is a Linux timing choice, not a decoded firmware frequency or
measured I2C bus speed. Original v6 source/DTB/schema evidence remains preserved
in AR's immutable build archive; its hash below describes that earlier draft.

Retained SQ2 DSDT CPXC has CAMP FSTATE0 GPIO17/18 tuples
`[pin,1,1,1,3,0]` (lines58771/58785) and FSTATE1 tuples
`[pin,0,0,0,1,0]` (59070/59056). Its GPIO13 MCLK tuple is at58883.
The existing SC8180X pinctrl driver supports cci_i2c on17/18 and cam_mclk on13;
its pull codes3/1 and drive code0 correspond to pull-up/pull-down and2mA.
Mapping the custom firmware action arguments to that register vocabulary is
an inference: the action decoder itself was not executed or independently
reconstructed. Both complete relevant firmware state sets are preserved.
The draft explicitly describes default/sleep CCI pins, uses output-disable
for GPIO input in sleep (the TLMM schema forbids input-enable), and holds rear
reset low in its default state. CCI currently does not select these sleep states
in its runtime callbacks; no physical pin or suspend behavior is established.

The local OV13858 binding draft describes the current driver's four data lanes,
19.2MHz clock, two link frequencies and three real supply dependencies. It
inherits the existing driver maintainer only as a routing hint; no appointment,
review or upstream approval is implied. Its endpoint has no remote CSI receiver,
so this control-only tree provides no capture path or video-node acceptance.
It omits the old prototype's clock-lanes7: the physical CSI clock-lane contract
still needs review when the receiver is integrated, not substitution by a guess.

Offline validation compiles nine added nodes and adds only four phandle
properties to existing nodes (CAMCC and the three LDOs). Every other property,
node and memory reservation compares exactly to the firmware-touch candidate.
Both disabled and enabled **offline schema fixtures** pass sensor/CCI/regulator
checks without diagnostics. Five enabled negative fixtures reject each missing
supply, an invalid CCI clock name and an invalid sensor lane count. Schema-document
validation passes. Including leds-consumer.yaml resolves the old focused subset's
missing LED type warning without modifying the common video schema.

Full TLMM validation retains seven diagnostic groups already present in the base
board: PCIe1/PCIe3, ALS input-enable, UART13/UART15, SSAM child names and four
SPI-HID pin node names. The draft introduces no diagnostic change. This is scoped
validation, not a claim of a clean full board schema. The failing initial reviews
and setup errors are retained alongside the final v6 evidence.

Draft DTB SHA256:
`daeba78c738eada2b10ec6898e719f41c1f82b5fc51353fbc288ec8439fd6c68`.
Base timing DTB:
`fc567fd1a7593d9b5b430dee4edb7086f3ef3f71179dd2c304801c6b5e49bd3e`.
The draft is checked against AR's frozen source manifest
`55cca7a964cd6111c121a39a8e5ed2a552be5c310e76fdf40ef8df31a0fb5eee`.
No hardware action was performed. Real CCI arbitration/interrupts, sensor ID,
rail sharing/error cleanup on hardware and capture remain open. Read AR's actual
result before choosing any next experiment; never enable the old all-camera tree.

The post-AR v7 disabled DTB is
`bd894ce7979c0ed47c3383861ecc24b42661facb9b6fbe775654ab5d920462df`.
The separately compiled enabled rear-only candidate is
`fa3b89f98697573d61bf23180bd81307de7e762e3a305b3240d087b4f4dc1561`.
Its only differences from v7 are CCI/rear status; focused schemas remain clean
and pre-existing TLMM diagnostics unchanged. This is an offline candidate,
with no install, selection or camera hardware result. Read
../AS-PLAN-20261003.md for normal-driver observation scope and provenance.
