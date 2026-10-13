---
name: spx-status
description: Report automatic Surface Pro X hardware coverage, actual failures and blockers honestly, separate from historical full acceptance.
---

# SPX status

Run `tools/spx/progress -v`. Keep the report at most one page:

1. First line: `boxes closed: N of 47; newly closed: IDs/none` (historical full
   acceptance). Next give automatic functional pass/total, inventory observed,
   blocked, failed and error counts with boot ID, release and report link.
2. State what usable hardware changed, the defect investigated, ruled-out
   hypothesis and next safe step. Builds, commits and test code are not hardware
   support. A scan pass is not pairing/transfer; H264 is not every codec/encode.
3. Explain missing support, fixtures/tools and known unsafe tests separately.
   No request for a human session: manual checks are outside this checklist and
   happen when the human wants. Battery tests remain deferred.
4. If stopped, state the concrete reason and what would allow safe continuation.

## Drift check

- Does every baseline/trial/recovery boot have its own complete validation
  report, or an explicit failed/missing status followed by a rerun?
- Is `AUTO-HW-CHECKLIST.md` generated from the same catalog and actual results,
  including blocked features? Are inventory rows incorrectly checked?
- Is hardware acceleration rejecting software fallback? Are untested codecs,
  encoding, real cellular data and acoustic output falsely described as working?
- Did an automatic test change network/firewall/display/power/driver state or
  retry a parked encoder/audio path outside `AGENTS.md` authorization?
- Did manual steps creep into the automatic checklist, or are synthetic input
  events being mistaken for physical behaviour?
- Are there bookkeeping TODOs/commits, redundant validator catalogs or repeated
  successful test variants rather than a real current defect?

Fix drift before reporting. Keep result files one page with links to generated
reports instead of copying their full tables.
