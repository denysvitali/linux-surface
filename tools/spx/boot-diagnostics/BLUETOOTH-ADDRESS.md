# Surface Pro X Bluetooth address setup

The retained 6.18 board source supplies this installation's address
`CE:27:F9:D2:B6:C9` because the Microsoft NVM contains a Qualcomm template
address. DT stores the six bytes in reverse order. This is a locally
administered installation address, not a recovered factory address or a value
to embed in a generic upstream board description.

On recovery boot `42966575-e6ec-4698-83c2-80e5aeb07011`, kernel
`6.18.3-1-surface+`, firmware loads and `hci0` exists, but BlueZ initially has
no controller. `btmgmt --index 0 config` reports missing `public-address`.
Setting the documented address makes the controller appear and report powered
on. An interactive `bluetoothctl` session starts discovery; no nearby devices
are found during the10s reference scan. The original soft block is restored
and Wi-Fi remains connected. Pairing and peripheral use are untested.

The per-installation boot tool [bluetooth-address.py](../bluetooth-address.py)
adds `local-bd-address` only to the single WCN3998 node in a copied DTB. A
mainline test is next; it does not change firmware or hardcode an address in
the kernel's shared board source. BG's shared UC trial stays disabled, and
Venus remains parked.

Recovery reference logs: `/var/tmp/spx-feature-readout-20261004/`.
Mainline acceptance still needs pairing, real HID/audio use as available,
reconnect, Wi-Fi coexistence and suspend/resume. Audio requires a separately
requested run. [Hands-on steps](PHYSICAL-TESTS.md).
