Mic capture evidence for AUDIO-ORACLE-RESTORED-20260928.md

Captured on Y boot b5f0a540-3e81-4415-b08c-f869e01349a2,
kernel 7.3.0-rc2-spx-mainline-20260927y+, on 2026-09-28 at ~00:25 local.
48 kHz mono S16_LE, DEC0 gain 84, captured on MM2 via plughw:0,1 with the
ALSA mixer routing applied. Verify with: sha256sum -c SHA256SUMS

  cap-live1.wav  DMIC0, 4 s. rms 3.6 / -79.2 dBFS / peak 27.
                 77% of energy below 300 Hz, peaks 11.7/128.9/175.8/199.2 Hz,
                 DC offset -0.48, centred sample histogram. Broadband analog
                 mic noise, not stuck data. This is the room floor.
  cap-DMIC0.wav  DMIC0, 2 s sweep run. rms 3.84 / -78.6 dBFS / peak 27.
  cap-DMIC1.wav  DMIC1, 2 s sweep run. rms 5.48 / -75.5 dBFS / peak 134.
  cap-ADC2.wav   ADC2 = AMIC2, which the DT routes to "Headset Mic", so this
                 is NOT an internal mic. 2 s. rms 22.53 / -63.3 dBFS / peak
                 448. Loudest input, but the wrong listener for speaker tests.

For reference, Y's last playback used a 4000/32767 peak tone = -18.3 dBFS,
about 61 dB above the -79 dBFS floor. Use a tone above ~8 kHz when judging
playback so it cannot be confused with sub-300 Hz mechanical noise, and
prefer a speaker-side DMIC over ADC2. Never play audio without the user
having asked for that specific run.
