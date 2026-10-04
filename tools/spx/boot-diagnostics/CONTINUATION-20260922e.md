# E continuation state — 2026-09-22

Automatic continuation after recovery remains **unverified**. The user manually
continued the Happy session while E was still running. The current boot is
`1caa8c4c-0fa9-4986-9e3b-32bf1919cea3`, with `spx_boot=mainline-trial` and
`spx_attempt=20260922e`; it is not a recovery boot. The user service journal
records that `spx-port-resume.service` was skipped because
`ConditionKernelCommandLine=spx_boot=known-good` was unmet.

The stale E marker has been archived, byte/hash-verified, and removed.
`spx-port-resume.service` is disabled using `systemctl --user disable` without
`--now`. No running Happy process was stopped or replaced, and no spawn API
request was made. The preceding D acknowledgement remains intact. There were
no files under `resume-spawn-requests/`; its state was checked unchanged.

Evidence archive:

```
/home/dvitali/.local/state/spx-port/continuation-archive/20260922e-1caa8c4c-0fa9-4986-9e3b-32bf1919cea3/
```

It contains the E marker and prompt, installed helper and unit, preceding
acknowledgement, current-boot user-service journal, request-state hashes,
`status.json`, and the hash manifest `sha256.json`.

## Next actual recovery boot

1. When preparing a new authorized attempt, archive its continuation prompt
   and arm a fresh marker with that attempt, the same Happy session ID, the
   current preboot ID, `prompt_path`, the repository `directory`, and
   `server_url: "http://happy.beago-bass.ts.net"`. Enable the reviewed user
   unit for the subsequent boot. Do not reuse E's stale marker or prompt.
2. The helper runs only on a different, known-good boot. It checks the local
   daemon identity and existing session, then server DNS/TCP readiness before
   claiming and submitting one local daemon spawn request. The daemon supplies
   its own RPC/session credentials. An ambiguous request is retained and is
   never automatically resubmitted.
3. The prompted turn must verify the recovery boot and first write
   `resume-ack.json` containing the exact attempt and current `boot_id`
   (optionally the same `session_id`). It then disables the unit without
   `--now`, archives the armed marker, and removes it. A manual continuation
   on the experimental kernel must not acknowledge a recovery boot.
4. Preserve the service journal and request record alongside that acknowledgement.
   An accepted HTTP response alone does not establish that the prompt ran.
   Keep pending or unconfirmed request records for investigation; never erase
   them merely to force another spawn.

The helper's 21 mocked tests and static verification of Happy's local daemon
API establish offline behavior only. No recovery boot has yet exercised the
complete daemon-POST-to-acknowledgement path.
