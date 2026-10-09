boxes closed: 3 of 47; newly closed: none.

# Promoted baseline bootloop: desktop audio startup isolation

**Observed:** promoted 7.3.0-rc2 boots reset repeatedly, roughly two minutes
apart. Last failed boot `0416c972-550d-48c4-92cb-4c543828037e` has no retained
panic, shutdown, or trial-return invocation. Its bounded startup collection
completed. Persistent logs end at about 52 seconds; that is not proof of the
exact freeze time. Recovery boot `f539fdc7-8957-4d6c-9bdb-eac37054621f`,
`6.18.3-1-surface+`, remains available.

**Lead:** the first reset followed enabling PipeWire/WirePlumber on boot
`c7ebfe0d`. These services now start on each baseline boot. ALSA discovery
is already disabled and the configured speaker sink is virtual; automatic
physical playback is not established as the cause. WirePlumber also enables
other device monitors and real-time processing is active.

**Changed:** restored the existing parked-audio startup guard for the five
PipeWire/WirePlumber services and sockets. This is one isolation change;
GNOME, the 7.x persistent default, and the disabled automatic return remain.
No watchdog changes, sound, microphone/camera capture, kernel build, or display
module operation. The full desktop speaker path is still outstanding.

**Isolation result:** boot `345b656b-807e-4cd4-bed6-d93335343c09`
reset again with PipeWire explicitly skipped. H-desktop-audio-startup is refuted.
Recovery is now `731e0973-b001-4972-84c9-eedaeae7ba67` on 6.18.

**Next change:** disable the trial checker on promoted boots (timer disabled,
CLI guarded, future promotion corrected). It changes CPU policy and probes
hardware at 50 seconds, so retaining it as a passive collector was wrong.
The check completed again; that does not exclude delayed effects of its work.
Journald now flushes every second rather than five minutes to preserve the
last seconds of an abrupt failure. This hypothesis still needs a 7.x boot;
the reset cause is not proven. Watchdog, GNOME and 7.x default remain enabled.
