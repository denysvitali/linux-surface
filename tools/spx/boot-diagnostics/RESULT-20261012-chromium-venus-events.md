boxes closed: 3 of 47; newly closed: none.

# Chromium initial event delivery localized

Boot93f93c82 unchanged,7.3.0-rc2-spx-mainline-20261004bg+.
Candidate365509377854 adds existing-gated timeout rawSTATUS/MASK/header and
independent12call sequence budget (max32payloadwords). Browser-only freshload;
no FFmpeg probe, encoder, sound/capture/reboot. NativeINIT/GET pass; Chromium
OUTPUT/CAPTURE initial96x96, hardwaredecode gate on, real1080p0frames/time0.
No SOURCE_CHANGE before close. Upon close, event arrives3133.875, parsed
1920x1088/count6/error0; callback waits instlock. FLUSHtimeout3134.880 shows
liveCPU0x4/unmaskedmask1e2 and MSGhead20bytes/type0x221006/SID0 (FLUSH_DONE),
rx0; SOURCE_CHANGE queued3134.896 aftertimeout unlocks. Thus teardown unread
response is explained by callback/parser head-of-line blocking, not lostIRQ.
Initial firmware event delayed untilFLUSH remains real defect; parserpayload
and IRQmask hypotheses refuted. No speculativequeue/IRQchange applied.
Browsercloseexit0, candidatesremoved/barrierremoved, bootunchanged. No full
playback pass. Next compare initial96x96 WORK_MODE1 vs successful1080pMODE2,
and splitheader buffers versuswholeAU for native firmware buffering.
MODE2onlya517381 sameChrome0frames/eventonlyFLUSH; refuted and reverted
70ce5c43. Nativewait/diagnostics retained. Alltestmodules/policy removed,
locksreleased, bootunchanged. No software fallbackclaim. Header/AU contract:
VenusH264 noCONTINUOUS_BYTESTREAM meansoneAU/buffer; Chromium152 splits
first1155byteAU into31SPS/9PPS/702SEI/413IDR buffers. Offlineuserspace patch
next; framingcause remains unproved until rebuiltbrowser trial.
Logs /var/tmp/spx-venus-browser-evidence-{kernel,browser}-20261012.log and
/var/tmp/spx-venus-mode2-{kernel,browser}-20261012.log.
