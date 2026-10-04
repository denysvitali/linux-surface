# R: bounded stage-8 runtime resume

Q completed the stage-7 PIO capability waiter on the P image. It did not
enter runtime resume or register the SLIM controller. R uses a distinct kernel
with `spx_probe_stage=8 spx_stage8_step=1 spx_pio_mode=1` and retains
`spx_allow_full=0`. Stage-8 step 0 is the default and stops before resume;
step 2 alone reaches `slim_register_controller()` and still requires
`spx_allow_full=1`. The selector is boot only (mode 0444).

Step 1 calls the existing runtime-resume path once. That may request QMI
power, start the PIO poll thread, read NGD version/status, and either use a
retained logical address or perform NGD setup and wait for the capability
exchange. It leaves the child's runtime PM reference pinned and stops before
the PM put and SLIM registration. No codec child enumeration or playback is
expected. The added power-up logs report which branch ran, using the status
value the code already read.

An explicit `stage 8 runtime resume done step=1` marker with state AWAKE is
required to pass the scoped test. A `stage 8 runtime resume failed` marker is
failure even if the outer child probe logs `enable done`: this staged path
keeps the child bound after a hardware mutation so probe-error cleanup does
not power it off or free callbacks while QMI/PIO state may be live. An absent
success marker, timeout, kernel fault, or controller registration is failure.
The automatic collector must archive that distinction. SSR DOWN and remove
still use their existing QMI/PIO teardown; no live unbind/rebind is planned.

Keep `spx-known-good` persistent, select R once, verify the recovery payloads
and R source/build/module/initramfs hashes, and archive the fresh boot before
choosing any next experiment. R is not a soundcard or audio playback test.
