boxes closed: 3 of 47; newly closed: none.

# Venus unpaced1080p H264 decode throughput

Boot6272005e-0a08-41e9-b9b6-2166ff0a04f1,
kernel7.3.0-rc2-spx-mainline-20261004bg+, candidatedcb395476b20/nativeOX1.
User requested throughput, not real-time pacing. Same Big Buck Bunny120s segment,
1920x1080 H264High30fps; explicit h264_v4l2m2m /dev/video32 qcom-venus.
No -re, null sink, -benchmark; decoder-only core/child loaded with scoped
coherent autoload barrier. No encoder, sound or capture. No constants changed.

Exit0:3602 frames decoded, zero errors;3598 output,120.00s media. FFmpeg
rtime15.653s, final230fps/7.67x; whole command16.138s. This is measured
end-to-end decode-to-null throughput for this clip/boot, not engine theoretical
maximum or display refresh rate. Output cutoff/drain count difference matches
paced trial; no full1080p output hash comparison claimed.

Post-unload journal has no new Venus warnings, refcount/OF/internal/hung errors.
Both candidate modules unloaded; policy removed, device lock free, boot unchanged.
Installed stack and persistent default unchanged. Logs /var/tmp/spx-venus-throughput-20261012-203813.log and
/var/tmp/spx-venus-throughput-20261012-203813-kernel.log. D03 stays open for other codecs/encoder/recovery.
