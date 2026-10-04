# WSA Smart Boost control read after the X stream fix

W's two post-result `amixer -c 0 scontrols` queries produced read-FIFO
underflows for register `0x312d` on the right WSA at 667 and 711 seconds.
The separate W snapshot records `soc_component_read_no_lock()` on
`sdw:0:0:0217:2010:00:4` for both. Register `0x312d` is
`WSA881X_BOOST_PRESET_OUT1`, used by the `Smart Boost Level` enum. That
control still used generic `SOC_ENUM`, whose getter calls
`snd_soc_component_read()` and attempts a physical SoundWire read. WSA's
existing shadow-backed PA-volume getter and register update helper do not
cover this enum. This explains the exact read path; no further live read is
needed to reproduce an already captured hardware failure.

The source now uses `SOC_ENUM_EXT` for `Smart Boost Level`. When a WSA
register shadow is active, its getter reads the shadow and its setter uses
the existing shadow-backed update helper. A setter for a currently unattached
slave returns `-ENODEV` before any bus access. In modes without a shadow, the
generic ASoC enum callbacks retain their prior behavior. The isolated
`make -j6 sound/soc/codecs/wsa881x.o` build passed. Source SHA256 is
`f7d46a6cbebf37c071b43c4709fea68e99032a22f740423f53a80dc51c5bb825`.

X remains the live, verified baseline. The fix is source-only until a distinct
kernel is built and booted. A later test should query the full mixer control
list and read the two `Smart Boost Level` instances with a separate archived
kernel delta. It should require zero new SoundWire read underflows and preserve
the attached-only silent PCM behavior. Physical playback remains unverified.
