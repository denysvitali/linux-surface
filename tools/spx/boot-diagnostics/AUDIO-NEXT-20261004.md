# Audio: corrected desktop bridge queued for BR

BR (`20261005br`) is installed with one consumed-once `serve` request:
`--serve-seconds 0 --desktop-peak 4000`. It retains the fixed mainline
`7.3.0-rc2-spx-mainline-20261004bg+` release, kernel and DTB. The SoundWire
shutdown helper now clears stale stream references (`c780c6f61362`).

The user heard low, interrupted sound on BQ. Its first startup suffered a
real ALSA underrun before public/default-sink handoff. Feeder `0b1778dbdce8`
now supplies silence during monitor gaps and preserves received stereo frames.
The ordinary digital limit is raised from 1433 to 4000 (+8.9 dB), using the
prior 6.18 clean-stereo findings. PA stays at minimum, WCD at 0 dB; temporary
test tones and acoustic/noise thresholds are unchanged. Volume implementation
is `326a4552df67`, queued-request forwarding `f91da6e7c677`.

On the next boot, inspect `audio/serve-ready.json` and `audio/serve-result.json`
under `/var/lib/spx-boot-diagnostics/functional/20261005br/`. Readiness requires
both the temporary desktop sequence and actual `spx_speakers` public-route
acoustic tests, a matching live PCM/boot ID, and a closed microphone. No
continuous recording runs during ordinary playback. A consumed request must
not be re-armed. Automatic return remains at uptime 900 independently of the
untimed audio bridge; persistent default remains `spx-known-good`.

BQ live reloads did not produce usable sound. Card reload reset WCD channel
lists while retaining mux selections; idle AIF2_PB -> ZERO -> AIF1_PB repaired
the two DAPM routes. ZERO alone (`ecdb75c19f02`) was insufficient. The last
retry initialized both amplifiers without underrun but detected no left tone.
Do not unload the WCD clock provider to bypass parked DSP ownership. Reopen,
WCD RX overflows and ADM capture-close timeout remain unresolved. See
[the BQ result](RESULT-20261004bq.md).

BP's bounded desktop and SoundWire-close check remains passed (A03a); BN
supplies the amps-off acoustic control (A01a/A02a). Full A01/A02/A03 remain
open. Useful listening volume, physical mapping/balance, repeated startup and
resume are not established by an installed candidate. Offline validation:
28 audio tests and 7 queued-request tests pass; the unchanged scorer's 13 tests
passed previously. No new acceptance box has closed.
