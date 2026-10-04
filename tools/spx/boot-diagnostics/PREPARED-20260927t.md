# T prepared: boot-time SoundWire force-attach

T is an exact S/R artifact reuse trial. Its private build archive rehashes
922 files and 272 symlinks against manifest SHA256
`64c76945a5a49701269d3798932ce25e528392cc3c05b4c0910c4c294ec033b5`;
all 202 installed module-tree files, R boot payloads and three known-good
recovery payloads match. The only command-line delta from S is the attempt
marker and `soundwire_qcom.spx_force_attach=1`. The worker path and limits
are in `AUDIO-SOUNDWIRE-FORCE-ATTACH-20260927.md`.

S's 314-file result archive was independently rehashed. Controller and card
registration passed, but both WSA slaves remained `UNATTACHED`/N/A. T has its
own 620-second result collector, 900-second fallback and exclusion from the
old 600-second return. It records worker markers and cached SoundWire slave
state, and distinguishes logical attachment from physical speaker playback.

Installed-state review passed with `spx-known-good` saved and `next_entry`
empty. No T boot is selected at this writing. Use only the archived one-shot
queue helper and its separate immediate pre-reboot guard. The user's standing
authorization covers a boot that may need manual power cycling; EFI-handoff
automatic recovery is not validated. Do not live-unbind display/SLIM devices
or write module parameters.
