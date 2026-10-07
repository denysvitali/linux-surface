# DX Bluetooth fixture enablement stops before discovery — no resume claim

**Change:** a85933fbe5ac adds fresh native Bluetooth discovery before/after one
normal AC sleep, using existing parked-audio sleep gates and owned unit. An
explicit fixture option temporarily enables the initially softblocked/off radio;
no power/rfkill repair is allowed between the two discovery windows.

**Observed:** boot `1c91d0d8-8b8f-41f0-b0f2-01eaffaf9fcd`, kernel
`7.3.0-rc2-spx-mainline-20261004bg+`. Fixture enablement fails a bounded BlueZ
command before either discovery window or sleep; whole owned unit16.347s.
QCA setup starts after unblock and completes normally, without a UART error.
A race between automatic native power-up after unblock and the immediate
Powered=true request is suspected; the private command reply was not recorded,
so the specific error is unconfirmed.

**Cleanup:** original radio power/policy/rfkill/WLAN and BlueZ identity restore;
owned scanner is reaped, all sleep masks/files/inhibitor and parked-audio
runtime-PM restore. No playback/capture or sleep occurred. Original fitted radio
softblock1/Powered=false/PowerState=off-blocked verified. No acceptance box closes.
Private observations retained at functional/20261008dx/bluetooth-resume-fixture-race/.

**Next:** bound and observe the native transition after unblock, avoid a
redundant power request, then make one changed functional attempt on this boot.
Keep this failure and its cleanup result; do not classify it as a resume fault.
