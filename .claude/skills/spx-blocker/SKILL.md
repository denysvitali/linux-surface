---
name: spx-blocker
description: Work one Surface Pro X defect in depth using automatic hardware evidence until it works or safe hypotheses are exhausted.
---

# SPX blocker: one defect, in depth

The goal is working hardware, not more tests. Mandatory per-boot regression
validation continues while this defect is investigated.

## Collect what is known

Read the defect in `TODO.md`, the generated check and latest boot report, the
feature entries in the findings index, the working 6.18 implementation and
prior result files. Keep one short brief of ruled-out hypotheses. Reuse working
code instead of re-deriving it. Distinguish an automatic probe missing a tool
from a driver missing support, and inventory from functional behaviour.

## Hypotheses

Keep one TODO per current defect and one per testable hypothesis: suspected
cause, one change/measurement and expected observation. Prefer a comparison
with working 6.18, a safe live measurement, a module reload, then a trial boot.
Observe the MMIO/debugfs and MSM hazards in `AGENTS.md`.

Test one hypothesis at a time. Mark it confirmed/refuted with the report link;
do not repeat refuted hypotheses with small test variations. After a boot,
inspect the full hardware-validation result before selecting the next trial.
A regression in another feature must be recorded, not hidden by a narrow pass.

## Close or stop

A generated functional row is checked only by its real test result on the
reported boot. Inventory and blocked dependencies never pass. Historical 47-box
acceptance is separate and cannot be claimed from a narrow automatic result.

Stop if all remaining hypotheses need unavailable information, a fixture or
unsafe operation. Record the best remaining lead and missing prerequisite.
Manual tests are outside the automatic checklist; do not wait for a human or
fabricate a stand-in. Mandatory regression checks are not permission for new
successful audio variants, encoder fault retries or battery tests.
