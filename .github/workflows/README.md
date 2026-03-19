# Surface Pro X Kernel Build - CI/CD

This directory contains GitHub Actions workflows for automated kernel building for Surface Pro X (SC8180X).

## Overview

The `build-spx-kernel.yml` workflow automatically builds the Linux kernel for Surface Pro X whenever code is pushed to `spx/*` branches. It uses:

- **Self-hosted arm64 runner** for native cross-compilation
- **Persistent git repository** - Zero re-clone bandwidth, only fetches deltas
- **Persistent ccache** (50GB) for fast incremental builds
- **Persistent source/build directories** to avoid full rebuilds
- **Automated pre-releases** with build artifacts

## Quick Start

### 1. One-Time Runner Setup

Run this on your self-hosted runner machine (once):

```bash
bash .github/workflows/runner-setup.sh
```

This creates persistent directories and configures ccache.

### 2. Trigger a Build

Push to any `spx/*` branch:

```bash
git checkout -b spx/test-build
git push origin spx/test-build
```

### 3. Download Artifacts

Build artifacts are available in two places:

**A. GitHub Actions Artifacts** (temporary, 7-day retention)
   - Go to Actions → Workflow Run → Artifacts section

**B. GitHub Pre-Release** (permanent)
   - Go to Releases → Find `spx-build-{sha}` pre-release
   - Download all assets

## Build Artifacts

Each build produces:

| Artifact | Description |
|----------|-------------|
| `Image.gz` | Compressed kernel image |
| `sc8180x-surface-pro-x.dtb` | Device tree blob for Surface Pro X |
| `modules.tar.gz` | Kernel modules (tar archive) |
| `config.log` | Kernel configuration used |
| `build-info.txt` | Build metadata (commit, timestamp, ccache stats) |

## Installation

```bash
# 1. Download all artifacts from the pre-release

# 2. Install kernel image
sudo cp Image.gz /boot/vmlinuz-linux-spx

# 3. Install modules
sudo tar -xzf modules.tar.gz -C /

# 4. Update initramfs (choose based on your distro)
sudo update-initramfs -c -k linux-spx     # Debian/Ubuntu
# OR
sudo mkinitcpio -p linux-spx               # Arch

# 5. Update bootloader (add entry for /boot/vmlinuz-linux-spx)
# For grub:
sudo update-grub

# 6. Reboot
sudo reboot
```

## Performance

The aggressive caching strategy provides significant speed improvements:

| Scenario | Time |
|----------|------|
| First build (cold cache) | ~30-60 minutes |
| Incremental build (small changes) | ~2-5 minutes |
| Module-only rebuild | ~1-2 minutes |

### Caching Strategy

- **Git repository**: Persistent clone in `~/kernel-builds/linux-surface-src` - only fetches deltas (~MB instead of ~4GB per run)
- **Ccache**: 50GB persistent cache in `~/.cache/ccache`
- **Build objects**: Preserved between runs for true incremental builds
- **No network overhead**: Zero upload/download of cache from GitHub Actions

## Bandwidth Savings

The Linux kernel repository is ~3-4GB. This workflow optimizes bandwidth usage:

| Approach | Bandwidth per run | 10 runs total |
|----------|------------------|---------------|
| Full clone each time | ~4GB | ~40GB |
| This workflow (first run) | ~4GB | ~4GB |
| This workflow (subsequent) | ~1-50MB | ~400MB |

**Savings**: After the first run, each subsequent run uses only 1-50MB of bandwidth (just the git delta), instead of re-downloading the entire 4GB repository.

This is achieved by:
1. **Persistent git repository**: The repo is cloned once to `~/kernel-builds/linux-surface-src` and reused
2. **Incremental fetches**: Each run only fetches the new commits, not the full history
3. **Local operations**: All checkout/reset operations happen locally with no network transfer

### Optional Pre-clone

To save even more bandwidth on the first workflow run, you can pre-clone the repository when running the setup script:

```bash
bash .github/workflows/runner-setup.sh
# Answer 'y' when prompted to pre-clone
```

This downloads the repository once during setup, so the first workflow run doesn't need to clone it.

## Maintenance

### Check Cache Stats

```bash
ccache -s
```

### Clear Caches (if needed)

```bash
rm -rf ~/kernel-builds
rm -rf ~/.cache/ccache
```

### Clean Old Releases

The workflow automatically keeps only the 5 most recent pre-releases. To manually clean:

```bash
gh release list | grep "spx-build-" | awk '{print $3}' | xargs -I {} gh release delete {} --yes
```

## Workflow Configuration

### Triggers

- Push to `spx/**` branches
- Manual trigger via `workflow_dispatch`

### Automatic Cancellation

The workflow automatically cancels previous runs of the same branch when a new commit is pushed. This:
- Saves runner resources and time
- Ensures only the latest code is built
- Prevents queue buildup from rapid commits

**Example**: If you push 3 commits in quick succession to `spx/v6.18`, only the 3rd commit will complete its build. The first 2 will be cancelled.

Note: Different branches run in parallel. Pushes to `spx/v6.18` and `spx/v6.19` will not cancel each other.

### Runner Requirements

- Self-hosted runner labeled `arm64`
- ~50GB free disk space for caches
- Linux OS with apt package manager

### Environment Variables

| Variable | Value |
|----------|-------|
| `CCACHE_DIR` | `~/.cache/ccache` |
| `KERNEL_SRC_DIR` | `~/kernel-builds/linux-surface-src` |
| `KERNEL_BUILD_DIR` | `~/kernel-builds/linux-surface-build` |

## Troubleshooting

### Build fails with "ccache not found"

Install ccache on the runner:
```bash
sudo apt-get install ccache
```

### DTB not found in artifacts

The device tree might not be compiled. Check the build log for:
```
arch/arm64/boot/dts/qcom/sc8180x-surface-pro-x.dtb
```

### Slow builds despite ccache

Check ccache hit rate:
```bash
ccache -s
```

If hit rate is low, the cache might be getting cleared. Verify permissions on `~/.cache/ccache`.

### Runner not picking up jobs

Verify the runner has the `arm64` label in GitHub Actions settings:
Settings → Actions → Runners → Labels

## Files

- `build-spx-kernel.yml` - Main workflow definition
- `runner-setup.sh` - One-time runner setup script
- `README.md` - This documentation

## Related

- Main repository: [linux-surface](https://github.com/linux-surface/linux-surface)
- Kernel source: linux-surface kernel tree v6.18.3
- Target device: Surface Pro X (Microsoft SQ2 / Qualcomm SC8180X)
