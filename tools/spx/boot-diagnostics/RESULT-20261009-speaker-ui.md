boxes closed: 3 of 47; newly closed: none.

# Missing desktop speakers: audio services deliberately inhibited

Boot `c7ebfe0d-89ec-4a57-b24f-daa6a2d080ea`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`.

**Changed:** read-only investigation requested by the user; no audio service,
PCM, mixer, boot setting or kernel change. No sound or capture.

**Observed:** ALSA lists Surface Pro X as card 1 and the ThinkPad dock as
card 0. The mainline baseline still boots with `spx_audio=parked`.
User service/socket drop-ins named `40-mainline-audio-trial.conf` contain
`ConditionKernelCommandLine=!spx_audio=parked`. systemd explicitly skipped
PipeWire, pipewire-pulse and WirePlumber because this condition was unmet.
`wpctl status` cannot connect; `pactl` reports connection refused.

**Meaning:** the verified WX speaker reopen fix did not restore ordinary
desktop audio startup. The promoted baseline retained the trial's desktop
inhibition, so GNOME has no running audio server to supply its output list.
This observation does not establish a speaker hardware regression.

**Next:** restore desktop audio service startup and the appropriate speaker
route as a separate requested enablement; account for existing legacy bridge
services and parked amplifiers before allowing playback. No new speaker
acoustic experiment is needed to explain the missing output list.

**Desktop startup restored (same boot):** user explicitly authorized ignoring
another session's device lock; that lock was left untouched. Changed the five
PipeWire/WirePlumber service/socket user drop-ins to inhibit mainline trial
boots instead of all parked-audio boots. All three services are active;
GNOME Shell Volume Control connected and `wpctl` lists Surface Pro X Speakers.
Selected `spx_speakers` as default, at 5% volume. Legacy bridge/PA services
remain inactive: the old bridge applies 44x gain and does not implement the
current native initialization. This restores output visibility only; the
existing virtual sink still has no physical speaker feeder. No PCM playback,
amplifier enablement, microphone capture or reboot. Physical desktop playback
integration remains outstanding; no acoustic acceptance claimed.
