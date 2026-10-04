# Privacy LED completion before camera start

C05 offline fix, 2026-10-03, after the actual AT trial and its known-good return.
Both the legacy `.s_stream` wrapper and native `.enable_streams` path previously
enabled the privacy LED after successful driver start. An asynchronous LED
request could also remain pending when the driver began producing frames.
The original source reproduces the ordering defect in both paths.

The V4L2 core now finishes a previous LED-off request, enables the indicator
and waits for provider completion before the first driver start. Suspended or
unregistering providers reject start. A blocking provider error is propagated
without calling the driver; failed LED enable or first driver start queues LED
rollback. Additional streams retain the existing light, including when adding
a stream fails. Successful partial stop retains it until the last stream stops.
Native failed stop retains the stream/light state. The legacy forced-success
stop behavior remains; the separate managed OV13858 failure fix asserts reset
and quarantines I/O before that path releases privacy.

`led_set_brightness_sync()` supports only blocking providers. Normal non-sleeping
GPIO LEDs have only `brightness_set`; V4L2 falls back to that API and flushes
pending work only when the blocking callback is absent. A real blocking callback
returning `-ENOTSUPP` remains an error. Checkpatch's single `ENOTSUPP` warning is
reviewed and retained: this is the actual LED API return (524), distinct from
`EOPNOTSUPP`. There are no other scoped style errors or warnings.

`check_stream_ordering.py` extracts actual V4L2 streaming, LED setters/worker and
GPIO callbacks. Its final ASAN/UBSAN harness passes **129 reachable-LED cases**:
atomic/sleeping GPIO, stale off work, provider faults, suspended/unregistering/
blinking state, legacy/native paths, invalid requests, stream failure rollback,
multiple streams and stop behavior. **72 LED-unreachable cases** check optional
support compatibility. Serialized work scheduling, bus writes and media locks
are models. These tests establish software ordering, not visible light timing,
electrical success, real capture, concurrent provider removal/suspend or one LED
shared across separate sensor objects. GPIO callbacks have no electrical error
readback. Physical operation and C05 acceptance remain open.

The first baseline helper compilation rejected an unused test counter; its
original helper/result remain preserved. Corrected exclusive legacy and native
baseline runs reproduce the intended original ordering assertion. The updated
rear integration harness also passes **171 lifecycle plus67 stream fault cases**
with the actual new V4L2 wrapper. Old archives remain unchanged.

Original V4L2 source SHA256:
`2c84b9ed11a10b584374e5d4b8192a58eda0387e18a638c530814614e24b9c60`.
Final V4L2 source SHA256:
`ba004f8b066b41a589644f35c738ebd5279323ed0953d0a4b0c2a249cded84b6`.
LED core, GPIO provider and sensor implementation are unchanged by this step.

Reproduce with a fresh output directory:

```sh
python3 tools/spx/boot-diagnostics/camera-privacy-20261003/check_stream_ordering.py drivers/media/v4l2-core/v4l2-subdev.c /var/tmp/spx-privacy-ordering-new
```

The native fixture was copied completely before source review/build. Its initial
review could not read the root-owned parent manifest; no source change or build
had run. A read-only privileged copy allowed verification against that manifest.
Only V4L2 source changes in the cloned fixture. ARM64 `W=1 KCFLAGS=-Werror`
and strict modpost/link validation passes all16 camera/support module targets,
with no build warning or missing-export suppression. The changed V4L2 object
and combined `videodev` module are rebuilt.
The retained September kernel export object and fixture release
`7.3.0-rc2-spx-mainline-20260922g` are an offline compile basis, not a full current
kernel build or a deployable candidate.

No module installed/loaded, GPIO/LED write, stream or reboot was performed.
Known-good UUID remains `74f8ed0e-be29-43fc-b8c1-9c9fa4e25d9b`; persistent default
is known-good with empty next entry and no BootNext. Receiver analog ownership,
physical LED/reset/fault behavior, capture and all47 acceptance checks stay open.

The162-file AT `offline-privacy-ordering-20261003` archive rehashes:
`923fec7fc621e5a256e2f547d74618ec2ecb24afb66c47f937d8029204fe8822`.
It preserves original/final source and helpers, original compilation rejection,
both baseline assertions, final harnesses/results, exact native command/config,
16 module/object artifacts, the changed V4L2 object and96,180 source entries.
Boot/default/empty next/noBootNext and all47 checks still open verify at freeze.
