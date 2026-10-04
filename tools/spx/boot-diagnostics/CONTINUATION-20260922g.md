# G native continuation verified — 2026-09-22

Happy automatically continued the same Codex thread after G booted. The visible
lowercase `continue` input was native startup injection, initially mistaken for
a manually sent user message. The task-specific resume helper never submitted
a spawn POST and was unnecessary for this continuation.

Identities:

- Attempt: `20260922g`
- Boot: `c17b7ebf-0dfd-47b7-a7d9-a5cddfa859db`
- Happy session: `cff5ed9402541cd71f9d24e77`
- Codex thread: `01a0c7d3-48d0-7172-aafd-5b0efdf567ee`

## Evidence

The session's read-only debug metadata reports
`resumeOnDaemonStart=true`, `resumeOnDaemonStartMessage="continue"`,
`startedBy="daemon"`, `startedFromDaemon=true`, and the existing Codex thread
above. The restored process, PID 2708, had exactly
`HAPPY_INITIAL_PROMPT=continue` in its initial environment. Only this whitelisted
prompt was inspected; credentials were not collected.

The daemon log records native `tryAutoRespawnStaleSession` at +0.115 seconds,
immediately after its machine realtime connection at +0.104 seconds. Process
start times from `/proc/PID/stat` place the daemon at boot +48.74 seconds and
the restored session at +49.39 seconds. The first resumed root tool ran at
about +67.6 seconds, approximately 18 seconds after session restoration.

The existing root Codex rollout contains the matching lowercase `continue`
input and the resumed tool calls. Happy server message envelopes, inspected
without retaining their content, cover sequence 1786 through 2285: all 500 are
agent messages, with zero user messages. Their recorded creation range is
10:16:33–10:47:53 UTC and spans F and G's resumed work. Thus the new Codex input
came from local startup injection rather than a new Happy app/user message.

Wall time stepped during startup. The rollout's startup input and later tool
timestamps can consequently appear out of order; use process start times,
journal monotonic timestamps, and rollout record order for the boot timeline.
The session stdout/stderr file is empty and was not used as execution proof.

The installed build's `enqueueCodexInitialPrompt` reads the initial prompt,
queues it with the source tag `daemon-startup-prompt`, and unsets the variable.
Its native daemon restoration supplies this prompt using the per-session
metadata above. The global-looking startup environment switch discussed in
the F review is not needed to obtain this observed behavior.

## Fallback retirement

The gate became ready at boot +48.699 seconds. The helper's first attempt
found no daemon state at +48.951, then correctly deferred when it found the
native restored session at +64.295. A two-second retry would also have missed
the restoration at +49.39; no retry change was made.

After confirming the marker was absent and the task unit was disabled and
inactive, these files were copied, hash-verified and removed:

- `~/.config/systemd/user/spx-port-resume.service`
- `~/.config/systemd/user/happy-daemon.service.d/90-spx-port-network-gate.conf`

Only `systemctl --user daemon-reload` was run. Happy's PID stayed 2692; no
process was stopped or restarted. The installed `resume.py`, repo source,
prior markers, gate evidence and history remain dormant. Spawn claims were
checked unchanged; none existed. Files named `manual-ack.json` in earlier
archives retain their historical names, which are not evidence of user input.

The whitelisted proof and its separately verified archive are at:

```
/home/dvitali/.local/state/spx-port/continuation-archive/20260922g-c17b7ebf-0dfd-47b7-a7d9-a5cddfa859db/native-continuation-review/native-continuation.json
```

The archive includes selected native daemon log lines, the last two root
continuation events and first tool timestamps, a server-envelope summary,
the retired unit/drop-in, a dormant helper copy, and `SHA256SUMS`.

## Read-only validation before the next boot

Run this command with its output captured rather than printing all metadata:

```
happy debug session cff5ed9402541cd71f9d24e77 --json --no-messages --no-diagnostics --no-process
```

The output contains multiple sections. Decode its first JSON object and retain
only `codexThreadId`, `resumeOnDaemonStart`, `resumeOnDaemonStartMessage`,
`startedBy`, `startedFromDaemon`, `hostPid` and `lifecycleState`. Require the
same Codex thread, native-resume flag `true` and prompt `continue` before
relying on this path. The command does not send a message or launch a session.
After the next boot, preserve the native restoration log and verify resumed
tools against the new boot ID. Do not re-arm the retired fallback to validate
the native path.
