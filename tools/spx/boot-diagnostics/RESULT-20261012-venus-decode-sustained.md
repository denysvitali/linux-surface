boxes closed: 3 of 47; newly closed: none.

# Venus isolated H264 sustained decode passes

Boot6272005e-0a08-41e9-b9b6-2166ff0a04f1,
kernel7.3.0-rc2-spx-mainline-20261004bg+, candidatedcb395476b20 with nativeOX1.
User requested Venus test. Reloaded matched core+decoder with scoped autoload
barrier; encoder never loaded. No simultaneous codec work, sound or capture.
No source/hardware constants changed. Decoder option explicitly h264_v4l2m2m,
/dev/video32 qcom-venus logged, not silent software fallback.

High-profile/B-frame fixture: all120 output size/MD5 hashes equal existing
software reference, exit0, zero decode errors. Then isolated Big Buck Bunny
source.mp4 H264 High1920x1080@30, real-time input,120s null sink:
exit0 after120.13s,3602 decoded frames/zero decode errors,3598 output frames,
120.00s output,30fps/1x. Output is decode-to-null, not visible panel playback.
Input starts0.066667s; bounded output/end-of-stream totals differ, so do not
claim every1080p frame hash checked or missing-frame acceptance established.

Post-workload AND post-unload journal has no new Venus warnings, refcount,
OF error, hung-task or internal error. Core/decoder unloaded successfully,
boot ID unchanged; policy removed, device lock released. Installed stack and
persistent baseline unchanged. No reboot or fault-producing encoder retry.
Logs /var/tmp/spx-venus-decode-20261012-203256-{high,sustained,kernel}.log,
hashes /var/tmp/spx-venus-decode-20261012-203256-high.framemd5.

H264 decoding now has exact fixture output and bounded sustained1080p evidence.
D03 stays open: other supported codecs, encoder CVP/protected-memory defect,
recovery/reset and full supported-path acceptance remain unresolved. No closure.
