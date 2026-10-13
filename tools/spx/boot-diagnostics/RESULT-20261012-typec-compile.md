boxes closed: 3 of 47; newly closed: none.

# Type-C offline compilation

Scoped candidate preserved in typec-scoped-WIP.patch. Revised proposed binding
now describes firmware routing ownership/asynchronous events only, not Linux
errno, retry behavior or missing controller implementation. This remains a
new binding proposal, not upstream-approved interface.

Compiled surface_aggregator_usbc.o and phy-qcom-qmp-combo.o against canonical
work-build with existing release/config: exit0, no compiler diagnostics.
This is object compilation ONLY, not fresh linked modules and NOT permission
to reload. Binding YAML parses. Isolated candidate DTS preprocessing and dtc compilation
pass (exit0); duplicate-unit-address and other tree warnings remain. Decoded
DTB contains mode-switch and firmware ownership on primary phy@88e8000.
Full dt-schema validation is unavailable: dt-doc-validate/dt-validate are not
installed. The candidate DTB is /var/tmp/spx-typec-candidate.dtb, NOT deployed.
No live module/DT deployment, display reload, reboot or captures.

Known limitations: port0 only, no initial-state query/PD contract, no USB-only
lane restoration after disconnect. HPD-low bypasses routing changes; scoped
QMP guards reject active-link changes. Hardware behavior remains unverified.
Sensor startup stays integrated. Venus reloads remain paused after fault.
