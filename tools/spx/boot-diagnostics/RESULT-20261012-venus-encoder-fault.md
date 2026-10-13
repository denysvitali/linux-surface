boxes closed: 3 of 47; newly closed: none.

# Venus encoder fault; recovery required

Boot6c15131e-36e5-415a-af0c-22d8a46122b2,
kernel7.3.0-rc2-spx-mainline-20261004bg+, native-HFIb7076dde3766.
H264 high-profile/B-frame decode passes all120 reference frame sizes+MD5,
following baseline120 exact match and clean unload/reload. Exposed formats:
decodeH264/VP8/VP9/HEVC/MPEG2; encodeH264/VP8/HEVC (enumeration, not passes).

H264 hardware encode from existing640x360NV12 film fixture,120frames/2Mbps,
failed with POLLERR/EIO. SFR NOC CVP access fault: PC1=PC2=22dd8,
ERRLOG2=bdbf0800 ERRLOG3=1808 CP_status1:0:0. No encoding pass.
Firmware evidence /var/tmp/spx-venus-encoder-fw.md proves PC after CVP engine
kick, not CPU bad dereference. ERRLOG2/3 fields/address origin not established.
Kernel-side bounded researcher active; no guessed mapping/range change.

Coordinator mistakenly started sustained1080p decode while encoder fault
recovery was incomplete. Both commands stopped; sustained test has no pass.
Root child kill was insufficient for sudo-owned descendants; explicit SIGKILL
issued. Encoder process zombie; decode probe11176 stuck D-state at
hfi_session_create ->venc_open, waiting core mutex. No force-rmmod; encoder/core
still loaded, decoder module removed. Device lock held during recovery.

No capture/sound/MSM reload or constants changed. Installed modules unchanged.
Fault logs /var/tmp/spx-venus-encode-fault{,-kernel}.log; decode hashes in
/var/tmp/spx-venus-native-high-20261012.framemd5 match existing reference.
Policy removed. Ordinary reboot requested; shutdown is queued, not completed.
Initial hash check used missing template path (failed); check with actual
20261010a/working-recovery.json subsequently passed both baseline/recovery
payloads and empty boot selection, after reboot request but before handoff.
Do not repeat reboot blindly. Recheck boot ID6c15131e and shutdown state first.
Vendor SM8150/Iris1 source requires protected encoder PERSIST allocation, unlike
Linux NS DMA; plausible CVP fault lead, not yet proven SQ2 contract/address.
Next: confirm clean7.x recovery then bounded allocation/first-buffer measurement;
no guessed secure mapping or unchanged encode. /var/tmp/spx-venus-encode-next.md.
