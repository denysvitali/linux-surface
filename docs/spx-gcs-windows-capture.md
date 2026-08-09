# SPX: Capturing the Windows dev-0x45 GCS/GLINK enable sequence

Goal: while the SPX runs Windows (Q6 ADSP is the same Microsoft-signed firmware),
capture the exact GCS/GLINK packets the host sends to the ADSP to enable dev-0x45
(built-in speakers). Use that to build a GCS client on Linux.

RE pre-summary (for context — verified by prior static RE):
  qcauddev8180.sys!GCS send fnptr storage offset = 0x12498 (.data)
  qcadcm8180.sys = AudioDspCalMgr (builds AFE/ADM cal + topology)
  qcslimbus8180.sys = SLIMbus QMI RPC (not a register driver)
  ADSP-side graph opcodes (per Agent B) sit in 0x00014001-0x0001400e range
  GCS send fnptr is loaded via `ldr x??, [x8, 0x498]` at many call sites in
    qcauddev (functions at 0x14005d7e0, 0x14005de58, 0x14005edb8, 0x14005ef38,
    0x14005f9f8, 0x140060198 (x2), 0x140060bc0, 0x140060e58, 0x1400610d8,
    0x140061248, 0x1400614a8, 0x140061650, 0x1400619d8, 0x140064530).
  WPP source paths embedded in the .sys:
    qcauddev = Z:\b\WP\AudioDeviceDriver\rel\10.5\Platform\src\AdieCodecDriverKMDF.c
    qcadcm   = Z:\b\WP\AudioDspCalMgr\rel\10.5\src\adcm_driver.c

================================================================================
TIER 1: WPP verbose trace (cheap, no debugger)
================================================================================
Captures the function call order + handle values when Windows enables the
speakers. ~5 min, no crash risk.

1. Find the WPP provider GUIDs (run on Windows, admin shell):
   ```
   logman query providers | findstr /I "qcom qualcomm audio"
   ```
   or PowerShell:
   ```
   Get-TraceLoggingProvider | Where-Object Name -Match "qualcomm|qcom" | Format-List
   ```
   If they're not TraceLogging providers (older WPP-only), use:
   ```
   logman query providers | findstr /I "auddev dspcalmgr adcm audio"
   ```
   Note: the SPX driver package may register them as
   "QCAudioDeviceDriver" / "QCAdcmDspDriver" or similar - any substring match
   on "qcom"/"qca"/"auddev"/"adcm" works.

2. Start a verbose WPP trace (replace GUIDs with the ones from step 1):
   ```
   mkdir C:\spx-trace && cd C:\spx-trace
   tracelog -start SPXAUDIO -f SPXaudio.etl -level 5 -flags 0xFFFFFFFF ^
            -guid <QCAUDDEV_GUID> <QCADCM_GUID>
   ```

3. Trigger the speaker enable (use any Windows audio app that exercises the
   built-in speakers - a YouTube video, a system sound test, etc.):
   - Open Settings -> System -> Sound -> "Test" on the built-in speakers
   - OR just play a music file in Groove / VLC for ~10s

4. Stop the trace and convert to CSV/evtx:
   ```
   tracelog -stop SPXAUDIO
   tracerpt SPXaudio.etl -o SPXaudio.csv -of CSV
   notepad SPXaudio.csv
   ```

5. Save C:\spx-trace to a USB stick; bring it back to Linux. The CSV shows the
   order of WPP-traced function calls, line numbers (which map to the .pdb
   symbol files), and the handle values passed in. Combine with the Agent A/B
   RE map to derive the call sequence.

================================================================================
TIER 2: WinDbg kernel break on the GCS send fnptr (THE GOLD)
================================================================================
This captures the byte-exact GLINK payload for every GCS command Windows sends
to the ADSP. ~20 min including WinDbg setup. Requires:
  - Windows booted on the SPX (or a Windows VM with the SPX drivers installed)
  - WinDbg from the Windows SDK
  - Kernel debug enabled (bcdedit /debug on + reboot) OR a WinDbg user-mode
    attach to the audio process running the speaker enable

=== STEP A: find the actual GLINK send function that 0x140022498 points to
The fnptr at 0x140022498 is a slot in qcauddev8180.sys's .data section. The
real function lives in a different module (qcdmdlls / qcomglinkstorlib or the
GLINK kernel-side driver). In WinDbg (kernel mode, after loading the .sys):
   ```
   .reload qcauddev8180.sys
   dps qcauddev8180+0x12498 L1
   ```
   Suppose it prints (example):  fffff801`12345678 qcdmdlls!GlinkSend
   That address is the real function we want to break on.

=== STEP B: set conditional breakpoints
   ```
   bp /p @$proc fffff801`12345678 ".printf \"GCS send: arg0(handle?)=0x%x arg1(payload?)=0x%x arg2(len?)=%u\\n\", @x0, @x1, @w2 ; .if (@w2 > 0 && @w2 < 0x10000) { .if (@x1 != 0) { db @x1 L @w2 } } ; g"
   ```
   Adjust register names after looking at the first few hits - the real arg
   order depends on the GLINK send signature. Typical ARM64 calling convention:
   x0 = handle/session, x1 = payload_ptr, x2 = payload_len. Log the first 5
   hits to learn the signature, then refine.

   If the function is a thin wrapper (in qcomglinkstorlib or similar), break
   a few instructions before the `ret` so you see all the call sites'

=== STEP C: also break on the standard APR send fnptr
   The legacy APR path uses fnptr at qcauddev offset 0x26600 (per Agent B).
   Capture the AFE/ADM cal commands too:
   ```
   dps qcauddev8180+0x12600 L1       # actual APR send function
   bp  fffff801`abcdef00 ".printf \"APR send: op=0x%x handle=0x%x payload=0x%x len=%u\\n\", @x0, @x1, @x2, @w3 ; .if (@w3 > 0 && @w3 < 0x10000 && @x2 != 0) { db @x2 L @w3 } ; g"
   ```
   (x0 may be the opcode, x1 the handle - inspect a few hits and adjust)

=== STEP D: also break on qcadcm8180.sys's cal send fnptr
   The cal manager (qcadcm) is the piece that builds the per-COPP cal blobs.
   If you can locate its APR send fnptr (same approach), break there too:
   ```
   .reload qcadcm8180.sys
   dps qcadcm8180+0x???? L1    # find the fnptr; the agent RE should give the offset
   bp ...
   ```

=== STEP E: trigger + capture
   - Clear the WinDbg log buffer
   - Trigger the speaker enable in Windows (sound test / YouTube / Groove)
   - Wait 5-10s for the trace to accumulate
   - Use .printf in the BP script so the trace ends up in the WinDbg Command
     window (not the kernel log). Copy-paste that window into a text file
   - Optional: `!dbgksave C:\spx-trace\kdbg.txt` to also dump the kernel debug log

=== STEP F: bring the file back
   Drop the WinDbg log (or .etl) in ~/Documents/spx-trace/. I can RE the
   captured payloads to extract the exact GCS opcode sequence + bytes.

================================================================================
TIER 3 (optional): static RE of the GCS fnptr callers
================================================================================
We already know the fnptr site (0x140022498) and 14+ callers in qcauddev. The
calling convention (aarch64) and the qcauddev disasm give us:
  - the WPP traces for each function
  - the payload structure (each caller sets up x0/x1/x2/w3 before blr)
  - the cal blob the caller reads from the ACDB
We can map fnptr callers to GCS opcodes in 0x14001-0x1400e by static RE. This
is what I'd do here on Linux if Tier 1+2 are unavailable; it can take several
hours of focused work and is not needed if you can do Tier 2 in 20 min.

================================================================================
What to do once you have a capture
================================================================================
Once you have the WinDbg log / .etl, bring it back and:
  1) Parse out the GCS opcode sequence + payload bytes per command
  2) Cross-reference with the Agent A/B RE of qcauddev + the ACDB extents
  3) Build a GCS GLINK client module (Phase 3 of the plan in
     /home/dvitali/.claude/plans/zazzy-wishing-hedgehog.md)
  4) Replay the sequence from Linux; hear audio
