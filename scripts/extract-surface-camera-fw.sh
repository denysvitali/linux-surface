#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# extract-surface-camera-fw.sh — extract Surface Pro X (SC8180X) camera
# firmware blobs from a Windows driver dump into the Linux firmware
# directory.
#
# Source: the Windows driver store dump, e.g.
#         /home/dvitali/Documents/drivers/FileRepository/
# Target: /lib/firmware/qcom/surface/
#
# This script only copies files. It does not configure the kernel or
# load modules. The blobs are required by any future SC8180X camera
# driver that implements the QC Spectra 390 ICP firmware load path
# and the QTI Chromatix tuning loader.
#
# Re-running is safe — existing files are left in place unless --force
# is passed. Requires write access to $FW_DIR (typically root / sudo).
#
# Files installed (8 total):
#   CAMERA_ICP_AAAAAA.elf           ICP firmware (Hexagon, non-stripped, 3.6 MB)
#   sensormodule.rfc_ov13858.bin    Rear (OV13858) module data (278 KB)
#   tuned.rfc_ov13858.bin           Rear (OV13858) per-unit tuning (2.0 MB)
#   sensormodule.ffc_ov5693.bin    Front (OV5693) module data (91 KB)
#   tuned.ffc_ov5693.bin            Front (OV5693) per-unit tuning (830 KB)
#   sensormodule.aux_ov7251.bin     IR/aux (OV7251) module data (52 KB)
#   tuned.aux_ov7251.bin            IR/aux (OV7251) per-unit tuning (376 KB)
#   tuned.default.bin               Default QTI tuning fallback (8.3 MB)

set -euo pipefail

# --- Configuration ---------------------------------------------------------

# Directory containing the Windows driver store (FileRepository/) dump.
SRC_DIR="${SPX_DRIVER_DUMP:-/home/dvitali/Documents/drivers}"

# Linux firmware destination.
FW_DIR="${FW_DIR:-/lib/firmware/qcom/surface}"

# Source INFs (the <name>.inf_<arch>_<hash> directories inside $SRC_DIR/FileRepository/).
CAMISP_SRC="qccamisp8180.inf_arm64_aeaf635adedd0c46"
CAMREAR_SRC="surfaceprox_camrearext.inf_arm64_0f417d24ce84193f"
CAMFRONT_SRC="surfaceprox_camfrontext.inf_arm64_b25026870ecde551"
CAMAUX_SRC="surfaceprox_camauxext.inf_arm64_753655592af436ec"

# Map of "source-relative-path -> destination-basename".
# Source paths are relative to $SRC_DIR/FileRepository/<inf>/.
# Destination basenames are placed inside $FW_DIR.
declare -A FILES=(
    ["$CAMISP_SRC/CAMERA_ICP_AAAAAA.elf"]="CAMERA_ICP_AAAAAA.elf"
    ["$CAMREAR_SRC/com.surface.sensormodule.rfc_ov13858.bin"]="sensormodule.rfc_ov13858.bin"
    ["$CAMREAR_SRC/com.surface.tuned.rfc_ov13858.bin"]="tuned.rfc_ov13858.bin"
    ["$CAMFRONT_SRC/com.surface.sensormodule.ffc_ov5693.bin"]="sensormodule.ffc_ov5693.bin"
    ["$CAMFRONT_SRC/com.surface.tuned.ffc_ov5693.bin"]="tuned.ffc_ov5693.bin"
    ["$CAMAUX_SRC/com.surface.sensormodule.aux_ov7251.bin"]="sensormodule.aux_ov7251.bin"
    ["$CAMAUX_SRC/com.surface.tuned.aux_ov7251.bin"]="tuned.aux_ov7251.bin"
    # tuned.default.bin is byte-identical across all three sensor ext dirs;
    # use the rear copy as the canonical source.
    ["$CAMREAR_SRC/com.qti.tuned.default.bin"]="tuned.default.bin"
)

# --- Argument parsing ------------------------------------------------------

FORCE=0
DRY_RUN=0
print_help() {
    cat <<EOF
Usage: $(basename "$0") [options]

Extracts the Surface Pro X (SC8180X) camera firmware blobs from a Windows
driver dump into the Linux firmware directory.

Options:
  --src DIR    Source driver dump (default: $SRC_DIR)
  --fw DIR     Destination firmware directory (default: $FW_DIR)
  --force      Overwrite existing files in destination
  --dry-run    Print actions without copying
  -h, --help   Show this help

Environment:
  SPX_DRIVER_DUMP   Same as --src
  FW_DIR            Same as --fw

EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --src)    SRC_DIR="$2"; shift 2 ;;
        --fw)     FW_DIR="$2"; shift 2 ;;
        --force)  FORCE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) print_help; exit 0 ;;
        *) echo "Unknown option: $1" >&2; print_help >&2; exit 2 ;;
    esac
done

# --- Pre-flight checks -----------------------------------------------------

if [[ ! -d "$SRC_DIR/FileRepository" ]]; then
    echo "ERROR: source driver dump not found at: $SRC_DIR/FileRepository" >&2
    echo "       pass --src DIR to point at a different dump" >&2
    exit 1
fi

if [[ $DRY_RUN -eq 0 ]]; then
    # Try to create the destination; if it fails because we lack permission,
    # re-exec under sudo.
    if [[ ! -d "$FW_DIR" ]]; then
        if ! mkdir -p "$FW_DIR" 2>/dev/null; then
            if [[ $EUID -eq 0 ]]; then
                echo "ERROR: cannot create $FW_DIR" >&2
                exit 1
            fi
            echo "Re-running under sudo (need write access to $FW_DIR)..."
            exec sudo --preserve-env=SRC_DIR,FW_DIR,SPX_DRIVER_DUMP \
                "$0" "$@"
        fi
    elif [[ ! -w "$FW_DIR" && $EUID -ne 0 ]]; then
        echo "Re-running under sudo (need write access to $FW_DIR)..."
        exec sudo --preserve-env=SRC_DIR,FW_DIR,SPX_DRIVER_DUMP \
            "$0" "$@"
    fi
fi

echo "Source:  $SRC_DIR/FileRepository/"
echo "Target:  $FW_DIR/"
echo

# --- Copy loop -------------------------------------------------------------

copied=0
skipped=0
errors=0
for src_rel in "${!FILES[@]}"; do
    dst_name="${FILES[$src_rel]}"
    src_path="$SRC_DIR/FileRepository/$src_rel"
    dst_path="$FW_DIR/$dst_name"

    if [[ ! -f "$src_path" ]]; then
        printf '  MISSING  %s\n' "$src_rel"
        ((errors++)) || true
        continue
    fi

    if [[ -f "$dst_path" && $FORCE -eq 0 ]]; then
        # Same size and mtime? treat as up-to-date.
        src_size=$(stat -c%s -- "$src_path" 2>/dev/null || stat -f%z -- "$src_path")
        dst_size=$(stat -c%s -- "$dst_path" 2>/dev/null || stat -f%z -- "$dst_path")
        if [[ "$src_size" == "$dst_size" ]]; then
            printf '  up-to-date  %-42s  %8d bytes\n' "$dst_name" "$src_size"
            ((skipped++)) || true
            continue
        fi
        action="updated"
    else
        action="copied"
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  %-9s %-42s  (would copy)\n' "$action" "$dst_name"
        continue
    fi

    if install -m 0644 -- "$src_path" "$dst_path"; then
        src_size=$(stat -c%s -- "$src_path" 2>/dev/null || stat -f%z -- "$src_path")
        printf '  %-9s %-42s  %8d bytes\n' "$action" "$dst_name" "$src_size"
        ((copied++)) || true
    else
        printf '  FAILED  %s\n' "$dst_name"
        ((errors++)) || true
    fi
done

echo
if [[ $DRY_RUN -eq 1 ]]; then
    echo "Dry run complete. Re-run without --dry-run to install."
elif [[ $errors -eq 0 ]]; then
    total=$((copied + skipped))
    echo "Done. $total firmware file(s) present ($copied copied, $skipped up-to-date)."
else
    echo "Done with $errors error(s). $copied copied, $skipped up-to-date."
    exit 1
fi
