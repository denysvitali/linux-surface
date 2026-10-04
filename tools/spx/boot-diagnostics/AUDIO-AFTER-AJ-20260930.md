# Next boundary after AJ

AJ still records a device0 write, now98 toBOOST_EN_CTL312a. put_pa_gain's guard
remains. set_port stores BOOST Switch's port_enable flag and calls boost_ctrl,
which writes312a and sleeps1.5ms without checking attachment. The other312a
writer is the PA sequence, whose callback already has an attachment check;
noPA/RDACDAPM marker occurs in AJ's frozen kernel log. The trace still does not
identify the caller or prove this submission caused the asynchronous error.

Next isolated source candidate: in set_port, reject only BOOST Switch changes
with-ENODEV when spx_enumerated_mode and slave status is notATTACHED. Put the
check before changing port_enable or calling boost_ctrl. Preserve attached/
nonenumerated boost behavior, allother software-only port selections, cached
reads and the existing gain guard. Do not globally gate cold-init writes.

Freeze AJ source/config/results before editing. Verify exactold/newcallbacks
with instrumented boost writes/delays, allfourports, enable/disable/nochange,
attached/nonattached/nonenumerated modes and write errors. Nativecodecobject
compile and source/config isolation checks required. Archive tests/source/logs.
Distinct AKcompletekernel/module/privateinitramfsbuild required beforehardware.
Reuse correctedAG/AI/ AJ DTB, pin2/native0/cmd_diagY and exactAJstrict620/900scope;
no simultaneous GPIO/address/routing/criteria change. ActualAJreturnmustbe
archived before deployment. No manual audio/PCM/input/capture or livechanges.
