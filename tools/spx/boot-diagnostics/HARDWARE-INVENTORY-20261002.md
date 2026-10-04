# AO hardware inventory, 2026-10-02

This is a read-only inventory supporting [PORT-CHECKLIST.md](../../../PORT-CHECKLIST.md),
not a functional test. Boot24d683f1-1493-44e1-a5b4-b7d7ed6e46ce,
release7.3.0-rc2-spx-mainline-20261001am+, attempt20261002ao.

| Area | Observed metadata | What it does not prove |
| --- | --- | --- |
| Storage | NVMe238.5GiB; EFI partition; LUKS/LVM root mounted | Sustained integrity, resume or full lifecycle |
| Display | eDP2880×1920; backlight interface; DP disconnected | Visual correctness, external output, blank/unblank; eDP enabled=disabled is a single idle-time sample |
| Input | Surface keyboard/touchpad, pen, IPTSD touch/stylus, power/volume keys, KIP tablet switch | Physical actions or detach/reattach |
| Audio | Surface Pro X sound card | Both speakers, capture quality or physical headset connector |
| Network | wlan0 connected; hci0 exposed; no WWAN class device | Throughput, Bluetooth peripheral use or cellular data |
| USB/Type-C | Six root hubs only; no Type-C class ports | Either physical port's data/PD/alt-mode behavior |
| Cameras | No V4L2 class devices | Absence of camera hardware; historical cameras remain unported here |
| Sensors | APDS9960 plus three PMIC ADC IIO devices | Stimulus response or motion-sensor coverage |
| Battery | ADP1 online; BAT1 capacity46%, Not charging | Charge/discharge operation; a charging policy may explain the instantaneous status |
| CPU/thermal | Two qcom-cpufreq-hw policies, performance governor; CPU/GPU/other thermal/cooling devices | Scaling, idle efficiency, thermal protection or an operational NPU |
| Remote processors | modem, cdsp, adsp running | Services, cellular data or full DSP functionality |
| RTC | Surface RTC enumerated | Time retention without NTP |
| Sleep | freeze/mem/disk listed; s2idle selected | Successful suspend/hibernate or wake |
| TPM/GNSS | No class device exposed | Whether the unit physically supports these functions via another interface |

Archive:
`/var/lib/spx-boot-diagnostics/attempts/20261002ao/hardware-inventory-20261002/`.
All22 files verified; manifest SHA-256:
`824b040394dda1ff74192733852eee946b3abfed38e5f0cf3993835ec311e8c2`.
The archive contains metadata JSON, command results, kernel journal, boot/attempt
identity, input-device descriptions (no input events), and the collecting script.
All six metadata commands succeeded; no hardware state changes were requested.

For a later baseline, `inventory-hardware.py` accepts a new private output
directory. It refuses an existing directory and verifies that the running
release/attempt matches the active attempt metadata. Its output does not mark
any checklist feature passed.
