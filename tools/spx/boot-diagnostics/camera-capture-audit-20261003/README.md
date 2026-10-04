# Rear capture dependency audit after AS normal probe

The [power-domain follow-up](PEP-POWER-DOMAIN-CONTRACT.md) traces selected PEP
footswitch/GDSC/MMCX client paths and retained startup lists. Eight domain
addresses/control masks agree with Linux;105 byte checks,183 actual helper
cases and ten rejected fixtures pass. Polling paths differ and dedicated analog
ownership remains unresolved. No receiver enable or hardware capture follows.

The [PEP clock follow-up](PEP-CLOCK-CONTRACT.md) resolves the raw firmware mode
and retained frequency plans: closest300 MHz selects400 MHz for CSIPHY and
300 MHz for its timer. The local table/PHY requests are corrected;85 instruction
checks,96 native cases and seven rejected fixtures pass. Dedicated analog
ownership and actual clock/capture validation remain open.

The [PEP loader follow-up](PEP-LOADER-CONTRACT.md) now traces the static STND
list/name conversion into table/device/action parsing. 76 original instruction
checks, a native 31-name model and four rejected export fixtures pass. Actual
Windows requests and resource execution/analog ownership remain unobserved.

The [receiver power follow-up](RECEIVER-POWER-CONTRACT.md) extends the earlier
CPXC-only scope to CPC0/CPC1/CPC2: MPCS four components/eight states, VFE0 thirteen
components/twenty-six states and all six retained PoFx callbacks. All 2,475 literal
packages and four negative fixtures verify. The clock follow-up above supersedes
its raw-number comparison. Actual Windows consumption and dedicated analog
ownership remain open.

Follow-up after AX's verified return: the [SQ2 ISP register contract](ISP-REGISTER-CONTRACT.md)
supports the existing Gen2 CSID/17x VFE register subset with47 instruction checks,
69 actual Linux macro values and four rejected profiles. Historical version
readouts/dummy-supply warnings are preserved with provenance limits. Receiver
analog ownership and current-candidate capture remain open. The original AS
audit context below is historical.

C01 evidence, 2026-10-03. AS actual boot29748fff-2312-42c5-982e-04bbd2304b52
normally identifies the rear OV13858 and idles its real three-rail supply path.
Its initial120.65s control evidence is independently verified; final620s baseline
and camera findings were pending when this offline audit began. No new trial,
controller enable, stream, bus operation or regulator write occurs in this audit.

`audit.py` re-extracts all986 literal CPXC packages from the hash-pinned SQ2 DSDT,
records CAMP's six states and confirms that none containsPMICVREGVOTE. Four
NPARESOURCE actions vote the camera/MMCX rail at firmware levels48/0; Linux CAMCC
already attaches toSC8180X_MMCX. This is a domain correspondence, not proof that
MMCX is the missing dedicated PHY/PLL analog provider. Do not invent that alias.

The historical v23 CAMSS node lacks every `*-supply` property. Its nine archived
capture files still match the pinned manifest. Current SC8180X CAMSS selects
`csid_res_sc8280xp`, whose eight CSIDs each requestvdda-phy/vdda-pll;
`camss-csid.c` obtains them with the normal regulator bulk API. The regulator
core's normal-get path can substitute a dummy when a supply is absent.
Thus prior raw captures do not establish those analog supply providers or
ownership. This source audit does not assert that a retained capture log contains
a dummy warning, or that missing supplies are physically unnecessary. Keep the
existing receiver supply requirement pending physical/SoC contract evidence.

The compiled v23 rear graph is reciprocal, but the lane namespaces differ:
sensor data1/2/3/4, receiver data0/1/2/3, receiver clock7. AS's identification-only
sensor omits its old clock7 and has no remote receiver. CAMSS parses the receiver
endpoint; do not copy the sensor's data-lane tuple into a new receiver description.
At this original audit, the SC8180X profile selector used the SDM845 GEN2 1.0
programming table and300 MHz PHY/timer requests. The later clock follow-up
corrects the PHY request to400 MHz; actual capture on the current7.3
implementation still needs validation. Sharing CSID/VFE tables does not prove
every SoC resource.

Next work needs actual analog rail/ownership or justified SC8180X power-contract
evidence, a complete receiver SID/binding review, then a rear-only graph with
real receiver resources, normal staged capture and idle/cleanup regression.
Front/IR physical supplies remain separate unresolved work. A placeholder/dummy
provider or removal of required analog rails would not resolve this dependency.
All47 hardware acceptance checks remain open.

The subsequent [DMA contract review](DMA-CONTRACT.md) resolves the SID/mask and
register/IRQ correspondence against retained SQ2 IORT, SMMU installation data
and DSDT. All16 masked streams and20 selected MMIO/IRQ resources are supported;
analog ownership and programming compatibility remain unresolved.

Reproduce offline with system Python/libfdt and a fresh output directory:

```sh
/usr/bin/python3 tools/spx/boot-diagnostics/camera-capture-audit-20261003/audit.py /var/tmp/spx-camera-capture-audit-new
```

The14-file output manifest is
`2dcb6b7655256e930590a6bf2d876e38caeaf391d4bde2a76125f13a7c821d7b`.
It preserves full input files, extraction, graph tuples, historical hashes and
scope limits; no full hardware acceptance follows from this offline review.
