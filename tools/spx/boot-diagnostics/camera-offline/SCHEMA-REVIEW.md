# Current binding review — 2026-09-22

The disabled extraction compiles, but it is not schema-clean and does not
provide deployable camera power integration. Existing schema files were used
unchanged. No core binding file was modified or a compatible fabricated to
force a schema match.

The broad `dt-validate -s Documentation/devicetree/bindings` scan timed out at
60 seconds before diagnostics. `schema-review-state.json` preserves the
command and timeout. A focused subset of the six schemas and their available
repository references completed in 1.425 seconds; exact command, files and
exit code are in `schema-focused-state.json`, output in `schema-focused.log`.
The validator is the existing local environment at
`/var/tmp/spx-dtschema-venv-20260915/bin/dt-validate`.

Concrete findings:

- `qcom,i2c-cci.yaml` rejects `qcom,sc8180x-cci` followed by
  `qcom,msm8996-cci`. The driver uses that historical fallback, but the first
  compatible is missing from the binding. Adding it alone would still require
  review of the appropriate clock-name/count conditional.
- `qcom,sc8280xp-camss.yaml` matches only SC8280XP. Therefore it did not check
  this SC8180X CAMSS node. Shared driver resource tables do not establish that
  the entire SC8280XP binding, including supply requirements, is correct for
  SC8180X. A specific binding needs review.
- No OV13858 binding exists in this tree. Its node had no specific schema
  coverage in this check.
- `ovti,ov7251.yaml` rejects the historical sensor endpoint `clock-lanes =
  <7>` (maximum 1) and the sensor's `orientation`, `rotation`, and
  `power-domains` properties. These values were retained for faithful review;
  do not adjust them merely to silence validation without examining sensor
  versus receiver lane semantics and power integration.
- OV5693 emitted no diagnostic in this focused disabled-node check. That
  does not verify its rails, communications or capture operation.
- The intentionally omitted supply properties are not permission to probe
  with dummy regulators. Disabled-node schema handling relaxes requirements;
  the physical rail dependency is still unresolved.
- The focused subset also prints `video-interface-devices.yaml: leds: missing
  type definition`; this is a subset schema-environment limitation, not a
  camera graph finding.

`dt-validate` returned zero despite the printed node diagnostics. The saved
logs, not that exit code, determine this review's limitations. No proposed
binding changes were made in this bounded phase. Direct-SPMI rail ownership
and a correct regulator/power sequence remain prerequisites for deployment.

## Follow-up controller drafts

`BINDING-DRAFT-REVIEW.md` records the later isolated CCI and CAMSS drafts,
including source resource-name checks and positive/negative schema validation.
This original log describes the unchanged-schema baseline. The new drafts
remain unapplied; sensor lane/power diagnostics, missing OV13858 coverage and
rail integration limitations remain unresolved.
