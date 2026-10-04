# Physical audio boundary after Y

Y verifies software transport, one attached WSA path, shadow-backed mixer
reads, and a successful one-second nonzero PCM submission. It does not verify
acoustic output. The signal was left-only, 1 kHz, 1% digital peak with 20 ms
fades, so an unheard or unattended run cannot establish silence. No USB
microphone is currently enumerated. AC was online and BAT1 was 47% during the
later review.

The older `linux-surface-kernel` work did establish real output on this same
device. Its `docs/audio/2026-09-08-clean-stereo.md` records microphone-confirmed
physical stereo on boot `83b2ba73-59f5-4fec-be8f-ed363e501781`. That was a
live repair without reboot persistence: physical right WSA at SoundWire
address 1, physical left at address 2, WCD GPIO direction/output registers
`0x42=0x1e` and `0x43=0x1e`, master DP1/DP4 bank 0, runtime frame 7, and an
LDO14E 1.8 V vote. It also verified desktop audio with separate 440/659 Hz
speaker tones. The labels of the force-attached left codec are not proof of
which physical speaker is powered: earlier single-amp tests heard the right
speaker while the `left_spkr` codec was bound.

Y differs materially: the force-attach worker deliberately leaves the
physical amplifier at enumeration address 0, and the core reports only
`sdw:...:3` logically `Attached`/1; `sdw:...:4` remains `UNATTACHED`/N/A.
The active codec maps DAC slave port 1 to master DP1. The current GPIO debug
view reports WCD gpio-1 and gpio-2 as **inputs**, while the older working
state used output enables. This does not by itself establish the physical pad
level. Y's base DT already declares LDO14E at 1.8 V, always-on, and the live
regulator summary reports one use; an absent LDO declaration is therefore not
the next isolated defect.

An internal-microphone probe could not open `hw:0,0` for capture: ALSA returned
`EINVAL` and the kernel reported no backend DAIs enabled for MultiMedia1.
It produced no samples, so the built-in capture path is not currently an
acoustic reference. Its 11-file archive manifest SHA256 is
`dc26a375d51b9b7ef1b758905141115fdb400a0f23047ae50626e95215034100`.

> **SUPERSEDED 2026-09-28.** The two sentences above are wrong, and so is this
> record's conclusion that no objective oracle is available. The capture path
> was never broken: the probe used `hw:0,0` (MultiMedia1) with no ALSA mixer
> routing, so `dpcm_fe_dai_open()` found no DAPM path to a backend DAI.
> Capture on `plughw:0,1` (MultiMedia2) with the routing applied works, and
> the internal mic is now a usable judge for playback with no listening report
> and no new hardware. See `AUDIO-ORACLE-RESTORED-20260928.md`; the method
> supersedes the listening-report step this record asks for. The measurements
> below are unaffected.

A separate one-second direct PCM tone at the previously microphone-tested
4000/32767 peak ran on Y with 20 ms fades, left channel only and the right
channel zero. `aplay` exited zero; DSP buffers, the one attached DAC port and
PA/RDAC events were recorded with no new FIFO or PA errors. AC remained online,
BAT1 at 47%, LDO14E at 1.8 V with one vote, and both WCD GPIO lines still
reported input/low before and after. The 19-file test manifest SHA256 is
`d6bfda06165be394565d5cf67065f72ff39e9d17efb501167f79046c4af578dd`;
independent review SHA256 is
`50e81a63c63812f00f45d4dd50b952bd88b7b59a75a5d9621efe2b14587cad92`.
No acoustic response has been reported. A listening report about that playback
or an attended repeat is the remaining observation: record tone, static,
click, or silence and which side. A positive observation establishes one
physical speaker path; a negative one at this level is more meaningful than
the 1% run but still cannot distinguish GPIO power, data-port routing, and
analog output without another control.

After that observation, isolate one boot-time hardware variable per trial.
The first candidate is known WCD GPIO pin enable state, because the older
working state drove pins as outputs and Y currently leaves them as inputs.
The existing boot-only `spx_swap_dac_master_ports` is a separate candidate to
route the single active stream to master DP4; do not change both together.
Any such trial needs a distinct one-shot entry, source/config and payload
archive, pre-reboot boot-ID/recovery hash checks, automatic result before
fallback, and an acoustic observation or external microphone to judge
physical output. The successful dual-address sequence should be ported only
after a single physical output path is characterized.
