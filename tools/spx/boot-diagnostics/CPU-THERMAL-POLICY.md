# Surface Pro X Linux passive CPU policy (WIP)

SPX chooses 75°C passive cooling with 5°C hysteresis for each CPU cluster.
These are Linux operating-policy choices, not recovered Windows thresholds.
The margin below the inherited 110°C critical trip is 35°C. Earlier cooling
may reduce sustained performance; hysteresis limits repeated boundary changes.
This does not establish a skin-temperature limit or the final thermal envelope.

The existing SoC zones identify cluster0/cluster1 as TSENS0 channels5/6.
CPU0–3 use cpufreq domain0; CPU4–7 use domain1. The cpufreq driver groups
CPUs by that domain, and the OF cooling driver registers the policy CPU's
node. CM observed CPU0/CPU4 cooling devices successfully enforcing/releasing
both policies, so the board maps cluster0 to CPU0 and cluster1 to CPU4.
The inherited 250ms passive polling and TSENS interrupt path remain in use.
Critical trips, GPU trips, LMh95°C policy and other SC8180X boards are unchanged.
No LMh IRQ linkage is required for this thermal-governor/cooling-device path.

The policy is unvalidated until real TSENS temperatures activate cooling.
For a bounded AC-powered test, first require valid cluster sensor readings,
step_wise policy, CPU0/CPU4 cooling bindings and a completed mainline boot.
Record temperatures, cooling states and CPU frequency limits during at most
180 seconds of load, stopping all workers at any sensor80°C or on error;
then observe recovery. Do not write emulated temperatures, cooling states or
trip values. Require each cluster's real75°C crossing, autonomous cooling-state/
limit change and subsequent release below70°C. A run that never reaches a
threshold is inconclusive; keep the policy and acceptance status honest instead
of lowering its threshold to manufacture a pass. Battery tests remain deferred.
