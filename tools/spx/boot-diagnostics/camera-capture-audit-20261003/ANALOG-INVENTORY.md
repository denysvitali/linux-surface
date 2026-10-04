# Receiver analog supply investigation

After AS's actual normal rear identification pass, a separate retained
PEP/PMIC inventory pins three SC8180X Windows binaries and extracts all986
literal SQ2 firmware CPXC packages again. The PEP strings contain MMCX rail
resources and four CSIPHY clock names. Camera packages retain MMCX and the
known sensor rail votes. These are bounded software observations, not a complete
call graph or proof that a dedicated analog receiver supply is unnecessary.

The [Qualcomm downstream SM8150 camera description](https://android.googlesource.com/kernel/msm/+/28cc5c521b21f92fa6f8a5a6be16960100f70a7a/arch/arm64/boot/dts/qcom/sm8150-camera.dtsi)
at a fixed commit names `pm8150l_l3` and1.2V for four PHYs. The full source is
retained and hashed. This is another SoC/PMIC topology, not the SC8180X/SQ2 board
contract; its provider name and voltage cannot establish SPX wiring or replace
the current receiver's two required supply references. No such DT change is made.

`audit_power_inventory.py` preserves all three original binaries, DSDT, parser,
camera package extraction, string offsets, full fixed-commit reference and source.
Its10-file output manifest is
`b570ff9414ad00312033c7ffc9e617513523c78ff91df46e37401eac59aa1c79`.
The receiver analog mapping remains unresolved. Next useful evidence needs the
SC8180X/SQ2 PHY power contract, actual board mapping or independently established
ownership; neither successful old raw capture nor related-SoC wiring suffices.
There was no binary execution, bus access, GPIO/regulator write or reboot.
C01 remains open.
