boxes closed: 3 of 47; newly closed: none.

# Venus raw command trace and firmware ABI

Boot6c15131e-36e5-415a-af0c-22d8a46122b2,
kernel7.3.0-rc2-spx-mainline-20261004bg+. Diagnosticfac728e7b561,
matching rebuilt core/dec/enc and scoped autoload barrier; same H264 fixture.

Observed INIT10007 SID0 domain2 codec2; INIT_DONE20006 SID0 error0.
Then SET11001 size32 property1001 input1 frame96x96; GET211009 size20
property202001. Immediately SYS_ERROR21001 SIDff event1 data1=1 data2=e2068,
SFR dxva_venus.c:1004:33394. Bufreq-input-110, zero frames,1.66s.
SID0 is proven accepted for init; no token change justified. Firmware disassembly
proves line1004 default unsupported-command branch, saved LR33394 hex.
GET211009 falls outside its accepted dispatch ranges. Actual pipeline from
incoming queue to this dispatcher is still being decoded; no packet-ID swap.

Vendor miniport constructs111001 codec-specific DXVA decode packets with
large codec state, copies unchanged. Its BUFREQ escape uses host calculations;
these are not yet mapped to Linux buffer types/layouts. Mainline Venus and Iris
gen1 both use211xxx generic stateful protocol.6.18 has no SC8180X Venus resource
or working decode proof; earlier 'working Venus reference' premise is false.

All candidates unloaded, no OF refcount error/host warning/reset in trial
journal, boot ID unchanged. Policy removed, installed modules unchanged,
locks free. No reboot/sound/camera/mic capture; no numeric hardware changes.
Logs /var/tmp/spx-venus-protocol-trace-{kernel,decode}.log.
Offline evidence /var/tmp/spx-venus-{assertion,protocol-next}.md.

Next: finish bounded firmware incoming dispatch/root translation analysis.
Do not suppress GET, aliasv6, invent host sizes or swap opcodes without a
complete supported ABI. No unchanged decode retry. D03 remains open.
