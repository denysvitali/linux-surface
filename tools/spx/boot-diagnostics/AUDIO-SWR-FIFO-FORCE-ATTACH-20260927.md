# W: use the existing serialized FIFO write path after force attach

V's readless WSA mode avoided the SoundWire core's failed INTMASK read, but
the first WSA cold-init write sequence saw a stale full write-FIFO count.
`qcom_swrm_cmd_fifo_wr_cmd()` already flushes and settles each write for the
Windows-init/core-enum paths because this bridged master's FIFO count is
unreliable. A narrow source change includes `spx_forced_attached` in that
existing branch. The flag becomes true immediately before
`sdw_handle_slave_status()` invokes WSA init. The force-attach worker's own
setup and all non-force modes keep their previous behavior.

Build a distinct W kernel release from the preserved source/config snapshot;
archive Image, all modules, corrected `0x2010` DTB, initramfs and logs. Reuse
V's command-line audio selectors, changing only the attempt marker. The
first criterion is WSA cold-init entry with no write-FIFO overflow and no
WSA status-update failure, at least one logical `Attached`/device 1, plus
controller/card, FD680/Wi-Fi/touch and a fault-free kernel. Record residual
read underflows and the PA-gain outcome separately. No pass can claim
speaker playback without an actual output test.

Use the standard one-shot GRUB selection and distinct 620s collector/900s
fallback. Retain `spx-known-good` as saved default and verify boot ID,
pending selection, hashes and recovery payloads before reboot. Do not
unbind live devices or change SoundWire module parameters on the running V.
