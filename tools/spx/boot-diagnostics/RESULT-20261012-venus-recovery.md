boxes closed: 3 of 47; newly closed: none.

# Venus fault recovery reboot confirmed

Current boot e61d4de7-37ae-4432-b5f9-079399782874,
kernel7.3.0-rc2-spx-mainline-20261004bg+, persistent spx-mainline7.x.
Previous boot6c15131e reached shutdown after authorized reboot request20:11;
Venus recovery worker still blocked in firmware PAS metadata DMA allocation:
CMA ->lru_cache_disable ->__lru_add_drain_all ->flush_work. It held core mutex,
blocking video-node open. Core mutex is a consequence, not proven root cause.
Previous system journal records repeated SIGINT then Ctrl-Alt-Del forced reboot
20:12:34 and watchdog pretimeout20:12:56. This proves shutdown escalation,
not which event ultimately reset the hardware. Pstore empty. Current desktop display-manager active, old ffmpeg absent,
locks free, temporary autoload policy absent, boot selection empty. Installed
old Venus core probes with-110; candidate decode fix remains committed/not
installed. Baseline boot is not a video-decode regression result for candidate.

H264 native-HFI baseline/high-profile B-frame120 hashes still recorded passing
on previous boot. Encode and sustained playback remain unvalidated.
Vendor SM8150 encoder requires protected PERSIST buffer; current Linux has no
ready protected heap/context path. Relevance to SQ2 and fault address association
not proven. No secure allocation, VMID/SID alias or hardware constants changed.

Offline diagnosis found no causal recovery/drain/core-lock cycle. LRU drains
have no Venus dependency; prior recoveries succeeded. Timer-sleep PIO also stuck
suggests broader wakeup disturbance; drain CPU/timer state missing. No recovery
patch justified. See /var/tmp/spx-venus-recovery-wait-20261012.md.
Encoder allocation/layout diagnostic dcb395476b20 integrated on spx/next;
canonical matched Venus module build passes (exit0). Not installed or loaded.
Existing opt-in flag gates32 allocation/query lines and first ETB/FTB only.
No hardware constants or functional allocation/protocol behavior changed.
Build log /var/tmp/spx-venus-encode-buffers-build.log; build lock released.
Fault-producing live trial remains deferred while recovery cause is unresolved. No unchanged encode run; no sound,
mic/camera capture, MSM reload or new boot selection. Full logs saved in
/var/tmp/spx-venus-encoder-previous-kernel.log. No box closed.
