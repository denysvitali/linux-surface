# AS rear-only identification trial

Read actual boot ID/cmdline and attempt.json before acting. Outgoing AR is
`5b14cce2-951f-4b43-a786-3cd2339f79b5`, release
`7.3.0-rc2-spx-mainline-20261003ar+`, with verified620.97s scoped baseline and
clean touch chronology. AS deliberately reuses that release, so uname alone
cannot distinguish these attempts. Never repeat a reboot-requested marker.

AS is installed with no boot selected at this record's creation. Live selection
and exclusive request/reboot-check markers establish later scheduling; an actual
incoming outcome requires a new boot ID and the exact AS command line. Known-good
remains the persistent default, and automatic EFI/early-kernel recovery remains
unvalidated under the existing authorization for repeated boots/manual-cycle risk.
All47 hardware acceptance checks remain open.

The complete AR build is copied exactly:908 files/272 links,193 modules/208 files,
96,798 independently streamed source records and54 exact embedded initramfs modules.
The existing AR module tree is reused without modification. Source/config/kernel/
initramfs are unchanged; AS is a new DT/command-line experiment, not a new kernel
build. The private initrd logger uses each live boot UUID and cmdline.

- Source archive: `488d6705fbdea620d59cdd67f73c63df5dcf9256a384e7a49cea1c421bf358f2`.
- Build manifest: `7e23c627c4b02ee44c0af9d8cc4e693133f510bebd49415d9f0e9b486c1d6df8`.
- Config: `0d315eff642a357d537b614ffd943955cd1700905a0ecf9b191401740a302fb1`.
- Kernel: `408515f77e82eac5803ccf7a6162d1c5a80d20deb1e1688afa3edc534f0fbe0e`.
- Initramfs: `ac00b9013eec27e6fda99fb125d506451993c81a2a68d56a9c1c2d6b6289065d`.
- Enabled rear-only DTB: `fa3b89f98697573d61bf23180bd81307de7e762e3a305b3240d087b4f4dc1561`.
- Embedded-config proof: `620504e2c79e6d288f64710d0d489ac8641d1fab5bb76b4cea1a6022b2317d0c`.

The DT adds only nine reviewed rear/CCI/pin nodes and four necessary new phandles
to existing CAMCC/provider nodes, preserving every other property/reservation.
Only CCI0 and the rear OV13858 are enabled. The three measured direct providers
remain at1.2/1.8/2.856V; no front/IR/CAMSS or guessed analog rails are added.
CCI0 source is explicitly37.5MHz, supported by CAMCC/CCI-v2 binding. Earlier AR
read-only summary showed inherited19.2MHz with no clock enables. The Linux rate
choice does not decode firmware PSTATE units or measure physical bus speed.
CCI sleep pin selection, physical sharing/ownership, sensor raw returned ID,
CSI clock lane contract, capture and full board/upstream schema review remain open.
Read AS-PLAN-20261003.md and the archived72-file candidate review for provenance.

The command line changes only attempt/boot-path identity and adds
`i2c_qcom_cci.dyndbg=+p` for the normal probe's CCI version log. The60s collector
records provider/21 PMIC controls; the120s collector preserves normal CCI/sensor
binding, PM, clocks, consumer/rail state and errors. At620s the finalizer also
requests a separate read-only final camera snapshot. It stops the900s fallback
only after the unchanged scoped baseline and initial/final camera findings pass,
with ordered phases and exact boot identity. Initial120 success alone is insufficient.
No manual bus reads/scans, streams, resets, rebinds, PCM or live MSM changes are
requested. A normal sensor bind implies its frozen probe passed the0x300a/0x00d855
ID check; raw ID bytes are unlogged, and CONFIG_FTRACE is disabled.

Offline checks preserve12 baseline AST expressions (1 positive/9 negative),
reject21 initial and21 final camera failures, six phase/timing failures and a
stale identity, and cover four baseline/camera truth-table cases. Actual boot-state
guard has2 positive/12 negative cases; complete freeze has1 positive/17 negative.
The first fixture alias and broad identifier-generation errors were retained and
corrected before deployment. The initial single-camera-snapshot review and outgoing
snapshot are preserved separately; only three runtime helpers changed for the
fresh final-camera policy. No hardware acceptance is inferred from these tests.

The final installed review verifies208 shared module files,5183 recovery files/
links and908 build files. Outgoing239-file snapshot manifest:
`57a26c858489603446b5b2302c075a373c462b1e4ab691539c49945d66807645`.
The24-helper final deployment manifest is
`5054f7054bc277b447244d3302520407e82296816680685ab18a701c57b820c3`.
The final full preboot guard also passed in actual systemd context without
SUDO_UID, in22.100s, bound to outgoing AR. Guard hash:
`42cc08a4c9055c51d56d8ca3d884bbbe9033d49584b08a4c7d6f9dafeed8929e`.
Verify current native continuation, freeze complete records and queue only with
queue-as-once.py. Its30s guard
rechecks actual outgoing identity, pending selection and all recovery/artifacts.

On continuation:

1. Read actual identity/cmdline, selection, attempt.json and reboot-check-passed.json.
   An AS incoming boot uses the AR release plus AS BOOT_IMAGE/spx_attempt identity.
2. Run review-as-handoff.py; absence of retained markers proves no callback/rail-off.
3. Review60s provider result with review-as-camera-provider.py and120s control with
   review-as-camera-control.py; preserve failures without forcing a probe or reset.
4. After620s run review-as-result.py, review-as-touch.py and
   review-as-camera-control.py --final. Distinguish inherited scoped baseline,
   clean touch chronology, combined trial result and physical camera acceptance.
5. If combined trial fails, keep900s fallback armed and preserve the actual return
   with a new identity-bound AS return archiver. Never blindly re-arm a failed image.
   On a pass continue camera receiver/supply integration and all remaining checklist
   features on a final common candidate. No capture or complete port is claimed here.
