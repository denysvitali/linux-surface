boxes closed: 3 of 47; newly closed: none.

# Venus standalone parameter-set flags

Boot `93f93c82-cdc5-40a6-a7ea-3fdeb4ec784d`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`; no reboot, encoder, sound or capture.

User requested avoiding a Chromium rebuild. Stopped its native build with
incremental outputs retained; installed browser and launcher flags unchanged.
Candidate `5bbd0e95d033` adds an opt-in Iris1 H264 MMAP-buffer classifier in
Venus: parameter-set-only SPS/PPS input receives the existing firmware
`HFI_BUFFERFLAG_CODECCONFIG`. Whole pictures, SEI and other codecs are unchanged.

This flag and separate SPS/PPS submissions are supported by the Iris1-era
Android path: MediaCodec queues each CSD entry separately, ACodec maps its
flag to OMX, SM8150 OMX forwards it through QBUF, and the Coral driver maps
it to the native HFI flags. Reference:
[SM8150 OMX input path](https://android.googlesource.com/platform/hardware/qcom/sm8150/media/+/b464f1f09ec2e24c3651e2de0c2dcf5e33e93a84/mm-video-v4l2/vidc/vdec/src/omx_vdec_v4l2.cpp#7659).
No source establishes that every standalone SEI is codec configuration.

Rebuilt coherent Venus modules incrementally in the canonical build directory,
with its existing dependency symbols and release name. Earlier build commands
needed correction for module-symbol dependencies and output location; the final
three-module link succeeds. Loaded only core and decoder with the old-module
autoload barrier and `spx_h264_codec_config=1`, under the exclusive device lock.

| Existing identical-byte input | CAPTURE buffers | OUTPUT dequeues | Result |
|---|---:|---:|---|
| Split SPS/PPS/SEI/pictures | 0 | 2 | SPS31/PPS9 accepted; select timeout |
| Whole AU control, same load | 60 | 62 | Normal decoding, no select timeout |

The split run still delivers SOURCE_CHANGE only during teardown and times out
on FLUSH. Unlike the previous unflagged split run (zero OUTPUT dequeues), both
parameter-set buffers now return. The first remaining unreturned buffer is the
702-byte SEI containing x264 user-data metadata. Codec-config flags for SPS/PPS
are therefore insufficient for browser startup; actual browser playback was
not retried with this insufficient candidate.

Core/decoder removed successfully, temporary policy removed, locks released;
boot unchanged. Logs: `/var/tmp/spx-venus-codec-config-{split,au-control}-20261013.log`
and `*-kernel-20261013.log`. Next: determine the native firmware contract for
standalone SEI before another kernel change. Browser AU patch remains a stopped
fallback; D03 remains open.
