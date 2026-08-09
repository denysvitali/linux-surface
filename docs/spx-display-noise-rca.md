# SPX sc8180x Display — Synthesis & SAFE Action Plan

> **RESOLVED 2026-06-22.** The display noise was caused by `arm-smmu.disable_bypass=0` in the kernel cmdline. With that flag removed, the main (audio) DTB boots clean at native 2880×1920. The mdss SMR mask stays mainline `0x420`; widening it to `0x421` was the cause of the earlier black-screen boot and must not be re-applied. GRUB default is restored to the main entry; the `.orig` recovery entry is kept.

## 1. WHERE THE ASSISTANT MESSED UP

Three compounding failures. **(a) Two variables at once:** config C changed the mdss SMR mask (`0x420`→`0x421`, `sc8180x.dtsi:3011`) *and* removed `arm-smmu.disable_bypass=0` from the cmdline in the same boot, so causation was never isolable — the DT comment itself admits this (`sc8180x.dtsi:3005-3007`). **(b) Untested DTB on the DEFAULT entry with no auto-revert:** the experimental DTB landed on the boot path the firmware auto-selects, and when it black-screened pre-journald the user had to hand-pick recovery; there was zero automatic fallback (dossier:71-75). **(c) Root cause mis-attributed three times:** "hpd-absent-delay" (refuted — display was already native-res), then "odd-SID bypass to physical garbage" (refuted — DPU emits zero faults in fault-mode live boot, so it never drives unmatched SIDs at scanout), then the synthesis-lead's "pre-bind efifb-scanout redirect" (refuted by all three verifiers — efifb at `0x80600000` is CPU/MMU-written normal RAM, *not* an apps_smmu client, and the mdss SMR isn't even programmed into hardware until DPU bind at ~10.84s, so nothing exists pre-bind for any mask to redirect).

## 2. BLACK-SCREEN ROOT CAUSE (config C)

**Best-supported explanation (confidence ~0.65): a runtime translation abort at the first DPU commit (~11.2s), caused by mask `0x421` under fault-on policy — NOT a pre-bind firmware-scanout abort, and NOT an SME `-EINVAL` attach failure.**

What I verified and what changed vs the synthesis-lead:
- **The lead's mechanism is dead.** efifb is CPU-written RAM (`framebuffer at 0x80600000 ... 2880x1920x32`, confirmed live), has no StreamID, issues no apps_smmu transactions. The mdss SMR is programmed only at DPU attach (~10.84s). So "0x421 redirects in-flight bootloader scanout, well before msm-DRM binds" is mechanically impossible. All three adversarial checks independently refuted it; I concur.
- **No attach failure on the config-C DTB.** I re-derived `arm_smmu_find_sme` (match `((sid^0x800)&~mask)==0`; conflict `((id^id2)&~(mask|mask2))==0`). The **main DTB is the APR stack** — `q6asm-dais iommus = <0x2e 0x1b21 0x00>` (SID `0x1b21`, dtb line 3698). **`0x1b21` does NOT conflict with mdss `0x800/0x421`** → mdss attaches fine. (One verifier's "0xc01 conflicts" is real but applies only to the **.orig/AudioReach** DTB, which config C did **not** run — that DTB uses `qcom,gpr`/`q6apm-dais 0xc01`. So the -EINVAL landmine is a red herring for config C, though it IS a real reason never to put 0x421 on the .orig tree.)
- **Surviving mechanism:** at runtime the DPU/display block drives the odd display SIDs `0x801/0x821/0xC01/0xC21` (IORT `\_SB.GPU0` lists them, iort.dsl:416-468). At `0x420` those odd reads are *unmatched* → with `disable_bypass=0` (config B) they bypass to physical = recoverable **noise**; with fault-on (config C, default `=Y`) unmatched would fault — but the LIVE fault-mode boot shows **zero faults**, so the DPU is *not* driving odd SIDs in the working config. At `0x421` those same odd-SID reads now **match the mdss stage-1 context** and hit **unmapped IOVA** → translation abort at the first commit → DPU stall → **early black**, before journald persists (~30s). This is the only model consistent with: A clean, B noise, C black, and zero faults in the live boot.
- **Confidence is capped at 0.65** because there is no captured config-C trace (live cmdline has `ramoops.console_size=0` *and* `CONFIG_PSTORE_CONSOLE is not set`, so pstore is structurally empty even on healthy boots) and the two-variable change was never isolated.

**Single-variable test that would confirm (decisive):** boot config-C's exact main DTB+cmdline (audio + `disable_bypass` removed) but with **mdss mask reverted to 0x420**, on a non-default entry, with pstore console enabled. If it boots → 0x421 is the lethal variable (runtime abort confirmed). If it still black-screens → the mask is exonerated and the `disable_bypass` removal (fault-on acting on some audio/other unmatched SID) is the cause. The pstore trace's faulting SID + timestamp settles agent and timing: an **odd display SID at ≥10.84s** confirms the runtime-DPU model; nothing pre-bind is possible.

## 3. NOISE ROOT CAUSE (config B) — RESOLVED

H1–H4 (SMMU mask / disable_bypass-alone / audio-SMR displacement / UBWC-hbb / lpasscc) are **refuted** by direct evidence and arithmetic — confirmed by every verifier (mdss `0x800/0x420` matches only `{0x800,0x820,0xc00,0xc20}`; audio `0x1b21`/`0xc01`/`0x1806` neither conflict nor subset; UBWC hbb 15-vs-16 and lpasscc-okay fire in the **clean** boot too; zero faults in all boots). What survives:

**H-noise-1 (CONFIRMED): `arm-smmu.disable_bypass=0` causes GPU/DPU streams to bypass translation and read physical garbage.** The drm.debug trace in the noise boot shows the DPU committing a *correct* 2880x1920 XR24 **linear** frame at 355.5 MHz to a *translated* low IOVA (0x3301000) with **no fault and no underrun** — i.e. mode, link, clock, stride and IOVA are all right, yet pixels are wrong. That forces the corruption into the **framebuffer bytes / backing pages** (GPU render or swizzle), which is downstream of EDID and upstream of scanout. The decisive single-variable test booted the main (audio) DTB with `disable_bypass=0` removed and was **clean**, confirming the flag (not the audio DTB or the 0x420 mask) was the noise cause.
- **Result:** remove `arm-smmu.disable_bypass=0` from the default cmdline. Done.

**H-noise-2 (refuted as unnecessary): panel-edp AUX EDID-read probe race.** The `Detected LGD` (clean) vs `Couldn't read EDID` (noise) journal line was a real correlate, but it disappeared once `disable_bypass=0` was removed — so it was a downstream effect of the same root cause (probe ordering under the bypass flag), not an independent pixel cause. No EDID override experiment is needed.

**Free zero-risk discriminator on any boot:** `journalctl -b 0 -k | grep -E 'Detected LGD|Could.?t read EDID|arm-smmu|context fault'` and `cat /sys/class/drm/card0-eDP-1/modes`.

> Do **NOT** widen mdss to `0x421` to "fix" the noise — that is unrelated and is the prime suspect for the config-C black (§2).

## 4. SAFE EXPERIMENT — COMPLETED

The H-noise-1 test was executed as a non-default GRUB entry: main/audio DTB + clean cmdline (no `arm-smmu.disable_bypass=0`). The user reported a **perfectly clean boot**. `journalctl` on that boot showed `Detected LGD LP129WT112684` and zero SMMU context faults. The verified config was then promoted to the default GRUB entry; the `.orig` recovery entry remains intact.

## 5. BOOT SAFETY NET

The simpler manual safety net is currently deployed: the GRUB default points to the verified main entry, and a non-default "RECOVERY: known-good DTB, no audio" entry using `/boot/dtb/qcom/sc8180x-surface-pro-x.dtb.orig` is always present. If a future change breaks the default boot, the user can manually select recovery.

The grubenv auto-fallback described in the original runbook is still deployable if desired — every module is present (`loadenv/test/echo/sleep/configfile/read/fdt/normal/linux .mod` all in `/boot/grub/arm64-efi/`), grubenv is a writable in-place 1024-byte file on the shared ESP (`/dev/nvme0n1p1`), and `grub-editenv/grub-reboot/grub-set-default` exist.

**Deploy (copy-paste; never run grub-mkconfig — its `00_header` emits `insmod efi_uga`, broken on arm64-efi):**
```sh
# STEP 1 -- back up + install hand-written grub.cfg
sudo cp -a /boot/grub/grub.cfg /boot/grub/grub.cfg.bak.$(date +%Y%m%d-%H%M%S)
# edit /boot/grub/grub.cfg by hand

# STEP 2 -- seed grubenv to a clean known state
sudo grub-editenv /boot/grub/grubenv unset next_entry
sudo grub-editenv /boot/grub/grubenv unset boot_attempts
sudo grub-editenv /boot/grub/grubenv set boot_success=1
sudo grub-editenv /boot/grub/grubenv list   # verify

# STEP 3 -- success-marker unit (ensure no Requires=graphical.target cycle)
sudo install -m0644 /etc/systemd/system/spx-boot-success.service /etc/systemd/system/spx-boot-success.service
sudo systemctl daemon-reload && sudo systemctl enable spx-boot-success.service
```

**Limits:** the net catches **black/early-fail** boots (config C class), *not* "reaches graphical.target but panel is noise" (config B) — for noise-class regressions use a one-shot and judge by eye. Mutate grubenv **only** via `grub-editenv` (size must stay 1024 B or GRUB's FAT writer silently fails). ESP is 95% full (27 M free); prune old `sc8180x-surface-pro-x.dtb.*` snapshots separately.

## 6. RUNBOOK / RULES (so this never recurs)

- **One variable per boot.** Never change DTB *and* cmdline (or mask *and* policy) in the same test. Config C's whole ambiguity is this rule being broken.
- **Never make an unverified DTB/cmdline the DEFAULT.** Experimental = non-default menu entry or `grub-reboot <id>` one-shot only; default stays known-good until a clean boot + zero faults is confirmed across 2-3 reboots.
- **Arm the fallback before every experiment** and confirm `grub-editenv list` shows a clean state first.
- **Keep `.orig` as a recovery entry** even after a new default is promoted.
- **Capture logs from a failing boot:** pstore is currently useless for sub-journald failures — `ramoops.console_size=0` **and** `CONFIG_PSTORE_CONSOLE is not set` (verified). To get a pre-20s trace you must **(a)** rebuild the kernel with `CONFIG_PSTORE_CONSOLE=y` **and (b)** set `ramoops.console_size=0x40000` on the test entry. Until then, the earliest evidence is persistent journald (~20s, after root mount at ~17s) — read `journalctl -b -1 -k`. After any failure, read the faulting SID/timestamp; an arm-smmu context fault on an odd display SID (`0x801/0x821/0xC01/0xC21`) at ≥10.84s confirms the runtime-DPU/mask mechanism.
- **Free discriminators (zero-risk, any boot):** `journalctl -b 0 -k | grep -E 'Detected LGD|Could.?t read EDID'`; `cat /sys/class/drm/card0-eDP-1/{status,modes}`; `dmesg | grep -icE 'Blocked unknown|context fault|global fault'` (expect 0).
- **DTB SID rule:** the **main** tree is APR (`q6asm-dais 0x1b21`) — `0x421` does NOT -EINVAL there; the **.orig** tree is AudioReach (`q6apm-dais 0xc01`) — `0x421` **WOULD** -EINVAL/conflict there. Never blanket-apply a mask across both trees.
- **Hardware hazards (brick → reboot-only):** NEVER read MMIO `0x171c0000+0x2000` (slim-ngd, wedges CPU); NEVER read `/sys/kernel/debug/.../pinmux-pins` or `.../pins` on sc8180x (oops holds pinctrl mutex → all GPIO/bind D-state); NEVER run `grub-mkconfig` (emits `insmod efi_uga`, breaks arm64-efi); don't unbind the live card0 (Hyprland is live).

**Key files:** `arch/arm64/boot/dts/qcom/sc8180x.dtsi:2999-3011` (mdss mask + incident comment); `/boot/grub/grub.cfg` (live, hand-written, `set default=0`); IORT `/home/dvitali/Documents/acpi/surface_pro_x_sq2/iort.dsl:416-468` (display SIDs).
