# Camera CSI analog supply contract remains blocked

**Target:** C01–C05 frames, reusing the preserved6.18 v23 real-scene recipe.
Known sensor rails and receiver resource/SID work remain retained. No real
PHY/PLL provider mapping or justified internal-domain contract is available.

**New bounded finding:** retained qccammipicsi8180.sys interface query at RVA
0x4f50 uses GUID8d73ce35-93cf-4795-8db9-40bbe130d859/IOCTL0x2326a7. Its DriverEntry
caller0x2b028 uses the returned object for TraceEnable/CoreDbgEnable/EnableLog
registry reads. This lead supplies diagnostic configuration, not analog power.
Selected PrepareHardware calls resolve to normal WDF context/resource helpers;
this does not establish absence of other power operations. Published Microsoft
WDF function indices support those dispatch resolutions.

**Disposition:** dedicated SQ2 CSI power net/provider identities, voltage and
control ownership remain required, or authoritative proof of an internal
supply domain. Related-SoC providers cannot establish SPX wiring. No guessed
rail vote, dummy supply, removal of inherited requirements, capture or boot.
Cameras remain open. Move to another feature; revisit when this fact is available.

**State:** current known-goodf8c6a442/6.18; no device changes from this research.
Source: camera-capture-audit-20261003/ANALOG-INVENTORY.md and retained MIPI bytes;
Microsoft https://raw.githubusercontent.com/microsoft/Windows-Driver-Frameworks/master/src/publicinc/wdf/kmdf/1.33/wdffuncenum.h.
