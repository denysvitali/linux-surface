# Verified evidence

Archive: `/var/lib/spx-boot-diagnostics/attempts/20261002ap/camera-power-c01-20261003/`.
All104 files in `sha256.json` verify. Manifest SHA256:
`98d475cd312be301d82d7bae809d271fc611b25e7ed4074c77e0ec06a5caa042`.

Use `ov13858-ordered-supplies.patch`, `cci-sc8180x-binding.patch`,
`candidate-final/result.json`, `cci/result.json` and `native-link.json` for
the final change. `camera-power-cci.patch`/`checkpatch.log` and `candidate/`
retain the initial combined-patch/rollback version for provenance; they are
superseded by the separately reviewed final patches and tests.

Final outcome:11 power fault-injection cases, five positive/four negative CCI
schema cases, and strict linking of16 native camera/support modules pass.
The original driver fails the order test. Boot remains AP with no selected trial;
C01–C05 remain open for real power integration and hardware validation.
