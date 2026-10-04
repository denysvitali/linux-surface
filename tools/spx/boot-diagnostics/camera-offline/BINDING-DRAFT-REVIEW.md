# Offline SC8180X controller binding drafts — 2026-09-22

**2026-10-03 update:** the two-line CCI binding addition is now applied and
revalidated with five positive/four negative cases. CAMSS remains an unapplied
draft. The discussion below records the original state; its apply-check
reproduction expects that earlier source. See the
[current camera audit](../camera-power-20261003/README.md) for new evidence.

The CCI change is a two-line compatible/clock-group addition. The separate
CAMSS draft checks the resources already selected by the local SC8180X driver
and the retained v23 topology. Both drafts pass schema-document validation;
the disabled extraction has no CCI/CAMSS diagnostics with these drafts. This
is a bounded offline result, not a deployable camera description or a claim
that the entire extracted tree is schema-clean.

Only this directory and `/var/tmp/spx-camera-bindings-20260922` were changed.
The drafts are not applied to `Documentation/devicetree/bindings`, included by
active DTS files, installed, or deployed. No hardware action was taken. All
11 recorded active input hashes remained unchanged, including active config,
CCI/CAMSS sources, board/SoC DTS, the CAMCC provider and original binding files.

## CCI: smallest supported addition

`cci-sc8180x-binding.patch` adds `qcom,sc8180x-cci` in two existing lists:

1. The compatible pair ending in `qcom,msm8996-cci` (CCI v2).
2. The five-clock conditional shared with SC7280, SM8250 and SM8450.

The second addition is necessary: adding only a compatible would leave the
SC8180X clock tuple without its proper count/name constraint. The tuple is
`camnoc_axi`, `slow_ahb_src`, `cpas_ahb`, `cci`, `cci_src`. The v23 CCI0 node
maps these to existing SC8180X CAMCC symbols
`CAM_CC_CAMNOC_AXI_CLK`, `CAM_CC_SLOW_AHB_CLK_SRC`, `CAM_CC_CPAS_AHB_CLK`,
`CAM_CC_CCI_0_CLK`, `CAM_CC_CCI_0_CLK_SRC`, respectively. Each is in both the
SC8180X clock header and the provider's clock array. `TITAN_TOP_GDSC` is also
in the provider's GDSC array. The fallback already selects `cci_v2_data` in
`i2c-qcom-cci.c`; no new driver match or runtime change is necessary for this
binding addition. Existing CCI-v2 power-domain requirements remain intact.

## CAMSS: proposed description and unresolved scope

`camss-sc8180x-binding-draft.patch` creates a separate SC8180X schema. It does
not give SC8180X an SC8280XP fallback compatible or alter the existing
SC8280XP schema. SC8180X selects its own PHY resource table and PHY programming
profile, even though its local CSID, VFE and interconnect resource tables are
shared with SC8280XP. This is a reason to retain a distinct compatible, not
proof that the two SoCs have identical hardware.

The draft starts with the existing CAMSS binding vocabulary and constrains:

| Property | Local evidence |
| --- | --- |
| 40 clocks | Union of SC8180X PHY and selected CSID/VFE resource names |
| 20 register regions | Four PHYs plus eight CSID/VFE pairs |
| 20 interrupts | Same named subdevices, in the retained v23 ordering |
| Five power domains | Four full IFE domains plus `top` |
| Four interconnect paths | Explicit `icc_res_sc8280xp` selected by SC8180X |
| Four graph ports | PHY IDs 0 through 3 |

`binding-resource-audit.json` records exact equality of all five resource-name
sets between the disabled DTB and selected driver tables. The previous
`topology-review.json` and extraction manifest preserve actual addresses,
interrupts, provider arguments and graph equivalence to v23. The new schema
is not evidence that every unused lite/VFE path worked in historical captures.

The first four `reg-names` follow SC8180X's retained ascending PHY windows:
`csiphy0`, `csiphy1`, `csiphy2`, `csiphy3`, unlike the SC8280XP ordering.
The SC8280XP example and its addresses are not copied into the SC8180X draft.
The draft has no binding example yet; a complete example should be written
when its unresolved supply and IOMMU contract is reviewed. Its maintainer
entry is inherited from the existing CAMSS binding as a draft routing hint;
no maintainer review or approval is implied.

The single `iommus` entry is **provisional**. v23 used one masked stream tuple
`<&apps_smmu 0xa00 0x4e0>`, and the draft models that observed form with
`maxItems: 1`. A successful three-sensor capture and this mask do not establish
a complete SoC SID inventory or prove that one entry is the only valid future
representation. Review the SC8180X stream map before promoting this draft;
do not copy SC8280XP's 16-entry limit without corresponding SC8180X evidence.
This draft should not be treated as an upstream-ready hardware binding until
that issue and the supply description are resolved.

`vdda-phy-supply` and `vdda-pll-supply` remain required. The explicitly selected
CSID table requests both, and `camss-csid.c` obtains them using
`devm_regulator_bulk_get_const()`. They are absent even from the historical
CAMSS node. No dummy or fixed provider was added. Generic analog supply
descriptions avoid claiming SC8280XP's documented 0.88 V and 1.2 V values are
independently established for SC8180X. The provider, ownership and sequencing
of both CAMSS and sensor rails still need review. Sensor LDO14_A/LDO17_A/LDO1_A
history must not be mistaken for proof of the CAMSS analog supply mapping.

## Validation and retained failures

Reproduce with existing system Python/libfdt and the preserved dtschema venv:

```sh
python3 tools/spx/boot-diagnostics/camera-offline/validate_binding_drafts.py
```

`binding-validation-state.json` records seven exact commands, durations and
logs. Both unapplied patches pass `git apply --check`. `dt-doc-validate`
produces no diagnostics with repository reference schemas available. The
focused disabled-DTB validation removes the prior CCI-compatible diagnostic
and adds actual SC8180X CAMSS schema coverage.

Four deliberate negative checks establish the relevant constraints:

- Changing only controller `status` in a disposable DTB makes both missing
  CAMSS supplies fail the required-property check. That DTB exists only in
  `/var/tmp`; it was never installed, overlaid or used for boot.
- A wrong fifth CCI clock name is rejected.
- A wrong first CAMSS register name is rejected.
- Five receiver data lanes in `endpoint@0` are rejected.

The last check initially exposed a gap in the borrowed SC8280XP schema shape:
its per-port `properties: endpoint` constraints do not cover the addressed
`endpoint@0` nodes retained by v23. The SC8180X draft uses
`^endpoint(@[0-9a-f]+)?$` for both forms. No existing SC8280XP binding was edited
as part of this isolated task.

The following original diagnostics deliberately remain:

- OV7251 sensor-side `clock-lanes = <7>` exceeds its schema maximum of 1.
- Its `orientation`, `rotation` and `power-domains` properties are unsupported
  by the current OV7251 schema. Their physical/power semantics still need review.
- The focused schema subset warns about a missing type definition for `leds`
  in `video-interface-devices.yaml`. This is a subset-environment limitation.

OV13858 still has no binding in this tree. The disabled-node check relaxes
required properties; it does not validate missing sensor supplies. No sensor
node, lane value, power-domain assignment or supply omission was changed to
make validation quieter. The validator returns zero even when it prints DT
violations; the reproduction script checks expected/absent diagnostic text,
not just process exit codes.

The CCI patch can be reviewed independently. CAMSS remains a draft pending
supply ownership, complete SID scope and a justified example. Sensor binding
work and safe rail integration remain separate prerequisites for a camera
candidate. No camera node should be enabled on the strength of these checks.
