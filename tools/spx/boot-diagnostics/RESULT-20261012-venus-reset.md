boxes closed: 3 of 47; newly closed: none.

# Venus interrupted candidate/reset

Previous boot b9c406c9; current6c15131e-36e5-415a-af0c-22d8a46122b2,
kernel7.3.0-rc2-spx-mainline-20261004bg+. No coordinator reboot command.
451c34cff796 native-session polling candidate compiled successfully, but
coordinator core insertion was interrupted. No insertion result or candidate
startup/decode log survives. Polling behavior was NOT validated.

Previous journal supplies a concrete earlier fault: 19:29:22 Venus core
rmmod logged bad of_node_put on video-codec@aa00000 in genpd_release_dev,
and warned next put would underflow/use-after-free. Earlier 'clean unload'
claims meant command returned0; they were incorrect as kernel-health claims.
This is a candidate cause of later failure, not proven reset attribution.
Last persistent journal19:31:34; pstore and archived pstore empty. No final
panic/watchdog/reboot cause retained. Do not reload candidate unchanged.

Reset also left HEAD451c34 commit object empty and temporary Venus policy
zero bytes. Removed temporary policy; baseline installed core still fails
reset-110; baseline/default remains7.x. No build/device locks held.
No new trial, captures, sound, suspend or display operations. Offline worker
investigates OF/genpd ownership defect before any further Venus load.
Source/Git recovery must preserve damaged objects and retained patch.

Recovery: quarantined empty451c34 commit object in
/var/tmp/spx-reset-recovery-20261012; restored source from diagnostic parent,
reapplied retained worker polling commit as d2485a0c6984. Git connectivity passes.
OF bug proved: of_find_node_by_name consumes borrowed parent twice during
child discovery. Fixed in50af624d3d50 with of_get_child_by_name; existing child
put stays balanced. See /var/tmp/spx-venus-of-refcount.md.
Initial incremental rebuild exposed damaged generated objects. Module-scoped
make clean followed by coherent rebuild succeeds, no suppressed symbol errors.
Build lock released. No live validation yet; no hardware constants changed.
