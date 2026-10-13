boxes closed: 3 of 47; newly closed: none.

# GPU slowdown inspection

Boot: `c8158f7d-3e2d-40d5-8ac4-e8f8245b932a`.
Kernel: `7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** nothing on the device; read-only inspection. Device/build locks
are held by camera-front; no workload, governor change or modeset attempted.

**Observed:** GPU governor `userspace`, requested/current 461 MHz in all 20
samples over five seconds. Available range 177–514 MHz; min/max constraints
match that range. Transition statistics show use of 514 MHz as well.
`gpu-freq.service` selects userspace; the user's power-profile scripts select
461 MHz for balanced and performance. Current profile is balanced.
GPU and CPU cooling states are zero. Kernel journal has no observed GPU
fault/reset/GMU timeout. GNOME uses the card1 GBM renderer and obtained a
high-priority EGL context. External display is 3440x1440 at 49.987 Hz;
internal display is 2880x1920 at 60 Hz.

**Meaning:** lowest-frequency hypothesis refuted for this observation.
The existing policy holds the requested clock below the available maximum;
that alone does not establish the cause of the reported slowdown. External
50 Hz refresh is a possible contributor to perceived motion smoothness.
No frame-time or application rendering-path measurement was made.

**Next:** identify the affected app/action and display, then observe that
specific reproduction. Preserve the existing frame-pacing workaround until
a controlled comparison is possible with exclusive device access.

**Typing-lag follow-up:** CPU governor is schedutil, with big cores observed
at their allowed maximum 3.1488 GHz; no configured maximum-frequency cap below
hardware limits. Memory and I/O pressure are approximately zero, CPU pressure
about 1.4%. Five-second process deltas: kgx 45.6%, GNOME Shell 27.0%, desktop
audio helper 35.1% of one CPU core each. These are observations, not proof
of the latency cause. kgx and GNOME have MSM DRM clients with accumulated
GPU execution time; kgx uses GSK_RENDERER=opengl. Slow Keys and Bounce Keys
are disabled. Asked the user to compare plain-shell typing in a fresh tab
with typing inside Codex before selecting an application-specific change.
