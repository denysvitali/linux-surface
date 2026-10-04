# F continuation startup race — 2026-09-22

F booted `7.3.0-rc2-spx-mainline-20260922f+` with boot ID
`9ed25de5-fecb-499d-8ef6-c4f4ca29d08c`. The trial marker matched the release,
attempt and new-boot checks. This continuation was initially classified as
manual. G's follow-up investigation corrected that assumption: Happy's native
startup metadata supplies `continue`, the restored process receives it through
`HAPPY_INITIAL_PROMPT`, and the corresponding root Codex rollout contains the
prompt. The latest 500 Happy message envelopes spanning F and G contain no
user messages. Native continuation is verified; the task-specific fallback's
POST-to-acknowledgement path was never exercised. See `CONTINUATION-20260922g.md`.

The helper did not send a spawn request. No `resume-spawn-requests/` directory
existed. Its journal records this timeline, in seconds after boot:

| Time | Evidence |
| --- | --- |
| 31 | Happy daemon state was not yet present; helper returned 75. |
| 47, 62, 78 | Happy DNS/TCP was unavailable; helper retried before creating a claim. |
| 87 | Tailscale entered Running; initial MagicDNS requests still returned SERVFAIL. |
| About 91 | Happy daemon logged `tryAutoRespawnStaleSession` for the same session. |
| 93 onward | Helper observed the exact live session and deferred without replacement. |
| About 150 | Happy daemon's machine realtime connection finally succeeded. |

The daemon's log uses time relative to daemon startup at about boot +30 seconds:
it restored the session at +61.200 seconds and connected machine realtime at
+120.297 seconds. These clocks must not be confused. The restored process's
`HAPPY_SERVER_URL` was exactly `http://happy.beago-bass.ts.net`, matching the
marker. The daemon PID/argv and local port were valid. This was a startup
network/automatic-restoration race, rather than invalid daemon identity or a
wrong server origin.

The F service journal, marker, prompt, installed helper and unit, manual
acknowledgement and hashes were archived at:

```
/home/dvitali/.local/state/spx-port/continuation-archive/20260922f-9ed25de5-fecb-499d-8ef6-c4f4ca29d08c/
```

Its `startup-race-review/` subdirectory preserves the original Happy daemon
unit, selected startup log lines, binary identity and the review's own hash
manifest. The parent task disarmed the F marker and disabled the continuation
unit. This review did not start, stop or replace any Happy process or issue a
spawn POST.

## Controls and the candidate tested on G

Static inspection of installed Happy build `6ada5409b4bc` found
`HAPPY_RESPAWN_SESSIONS_ON_START` registered as a boolean whose default is
already false (`config.init.boolField.func63`, address `0x754470`). The config
field is offset `0x82`; no read of that field was found in the daemon functions.
The periodic stale-session reconciliation independently invokes
`tryAutoRespawnStaleSessionInternal`. Setting that apparent startup switch to
false is therefore not an evidence-based fix for this observed scan.

The installed CLI exposes no send-prompt command; inspected local daemon
handlers expose spawn/restart/stop/session-started operations, with no prompt
delivery handler. An internal `SessionSyncClient.SendUserMessage` exists, but
using it externally would require implementing Happy's authenticated session
protocol. No such path was added or tested against the live session.

The candidate prepared after F was `resume-daemon-gate.conf`, which invokes
`resume.py --daemon-preflight` before daemon startup. Only an authorized new
armed boot with an explicit server origin waits, for at most 180 seconds.
Unarmed or mismatched boots return immediately. A timed-out gate records its
failure and still permits normal Happy startup. The gate never accesses
credentials, sends a prompt, creates a spawn claim, or changes the live-session
guard. It prevents the measured F network delay from consuming the daemon's
initial scan interval, but remains a timing-based candidate pending a real
trial. G subsequently showed that native restoration runs immediately after
connection and already injects its own prompt; the assumed initial scan window
was not reliable. The installed gate and fallback unit were then archived and
retired. A successful TCP probe alone does not prove end-to-end prompt delivery.

All 35 mocked continuation tests pass, including hung DNS at the gate deadline,
matching/mismatched trial authorization, disarming during a wait, unchanged
marker/claim state, live-session preservation, and ambiguous POST retention.
No drop-in was installed and no service was restarted during this review.
