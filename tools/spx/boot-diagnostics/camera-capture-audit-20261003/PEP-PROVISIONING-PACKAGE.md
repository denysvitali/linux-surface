# PEP provisioning package: processor policy only

The retained `surfaceprox_pep.inf_arm64_6f779ee9c199c1af` driver package
installs `PPMSettings-8180Profiles.wd.ppkg`. This was not covered by the earlier
CPXC/PEP camera power analysis. Offline extraction on October6 finds one
XPRESS-compressed WIM image, `Power.Settings.Processor`, dated June7,2019.

`CommonSettings/1/AnswerFile.xml` and the generated
`Multivariant/0/Prov/RunTime/0__Power_Policy.provxml` contain only processor
policy: heterogeneous scheduling thresholds, initial performance, decrease
time, minimum/maximum performance and profile-specific maximum frequency.
The other XML files describe the package and reference that policy.
The two substantive inputs are retained in `ppm-settings/` beside this note.

There is no camera device association, regulator identity, voltage vote,
CSI PHY/PLL supply or camera power-domain mapping in this package. It supplies
no missing analog provider and does not justify a camera rail patch. It also
does not specify CPU thermal trip temperatures. Camera power ownership remains
unresolved; no capture or acceptance test was performed.

The installed archive reader did not support WIM. A package-manager attempt
failed on stale mirror URLs before committing changes. The upstream
[wimlib1.14.5 source](https://wimlib.net/downloads/wimlib-1.14.5.tar.gz) was built
locally in `/var/tmp/spx-wim-reader/`, with `--without-ntfs-3g --without-fuse
--disable-shared`; nothing was installed or applied to Windows/Linux policy.
`wimlib-imagex info`, `dir` and `extract … 1 --dest-dir=… --no-acls` read the
package, and every extracted XML file was parsed and inspected.
