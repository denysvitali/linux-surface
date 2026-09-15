#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Fail-closed checks for watchdog-guarded SPX kexec test boots.

This tool is deliberately read-only.  It validates an artifact manifest and,
unless --offline is used, the live guardian boot.  It never loads or executes a
kexec image; that remains prohibited until the one-time expiry test described
in KEXEC-RECOVERY.md has produced a recovery record.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess

TARGET_WATCHDOG_COMPATIBLE = {"qcom,apss-wdt-sc8180x", "qcom,kpss-wdt"}
GUARDIAN_WATCHDOG_COMPATIBLE = {"qcom,apss-wdt-sm8150", "qcom,kpss-wdt"}
REQUIRED_CMDLINE = {
    "panic=10",
    "oops=panic",
    "rootwait",
}


def require(condition, message):
    if not condition:
        raise SystemExit("BLOCKED: " + message)


def command(*argv):
    try:
        return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise SystemExit("BLOCKED: command failed: " + " ".join(argv)) from error


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_image_header(path):
    with Path(path).open("rb") as stream:
        header = stream.read(64)
    require(len(header) == 64, "kernel Image is shorter than its ARM64 header")
    fields = struct.unpack("<IIQQQQQQII", header)
    text_offset, image_size, flags, magic = fields[2], fields[3], fields[4], fields[8]
    require(magic == 0x644D5241, "kernel does not have an ARM64 Image header")
    require(image_size > 0, "ARM64 Image has an ambiguous zero image_size")
    require(flags & 1 == 0, "big-endian ARM64 Images are not supported")
    return {"text_offset": text_offset, "image_size": image_size, "flags": flags}


def validate_artifact(item, label):
    path = Path(item["path"])
    require(path.is_absolute(), f"{label} path is not absolute")
    require(path.is_file(), f"missing {label}: {path}")
    require(sha256(path) == item["sha256"], f"{label} hash mismatch: {path}")
    return path


def validate_manifest(manifest):
    require(manifest.get("schema") == 1, "unsupported manifest schema")
    kind = manifest.get("kind")
    require(kind in {"guardian", "mainline"}, "manifest kind must be guardian or mainline")
    require(manifest.get("loader") == "kexec_file_load",
            "manifest must require the audited kexec_file_load path")
    release = manifest.get("release", "")
    require(release and not release.isspace(), "manifest lacks a kernel release")
    image = validate_artifact(manifest["image"], "kernel Image")
    initrd = validate_artifact(manifest["initrd"], "initramfs")
    dtb = validate_artifact(manifest["dtb"], "device tree")
    require(not manifest["image"].get("gzip", False),
            "kexec guardian requires a raw ARM64 Image, not an EFI/compressed image")
    header = read_image_header(image)
    require(release.encode() in image.read_bytes(),
            "kernel Image does not contain the manifest release")
    require(f"Kernel: {release}" in command("lsinitcpio", "-a", str(initrd)),
            "initramfs release does not match the manifest")
    cmdline = set(manifest.get("cmdline", "").split())
    required = REQUIRED_CMDLINE | {f"spx_boot={kind}-kexec"}
    missing = sorted(required - cmdline)
    require(not missing, "target command line lacks: " + ", ".join(missing))
    require(any(x.startswith("root=") for x in cmdline), "target command line lacks root=")
    compatibles = set(command("fdtget", "-t", "s", str(dtb),
                              "/soc@0/watchdog@17c10000", "compatible").split())
    expected_compatibles = (TARGET_WATCHDOG_COMPATIBLE if kind == "mainline"
                            else GUARDIAN_WATCHDOG_COMPATIBLE)
    require(expected_compatibles <= compatibles,
            f"{kind} DTB lacks its audited Qualcomm watchdog compatibles")
    return {"kind": kind, "release": release, "image": str(image), "initrd": str(initrd), "dtb": str(dtb),
            "cmdline": manifest["cmdline"], "header": header}


def config_value(name):
    return command("systemctl", "show", "--value", "-p", name)


def validate_live_guardian():
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    boot_start = command("uptime", "-s")
    age = float(Path("/proc/uptime").read_text().split()[0])
    cmdline = Path("/proc/cmdline").read_text().split()
    require(any(x in cmdline for x in ("spx_boot=known-good", "spx_boot=guardian-kexec")),
            "known-good source boot is not running")
    require(age >= 120, "source boot is less than two minutes old")
    with gzip.open("/proc/config.gz", "rt") as stream:
        config = set(stream.read().splitlines())
    require("CONFIG_KEXEC=y" in config and "CONFIG_KEXEC_CORE=y" in config and
            "CONFIG_KEXEC_FILE=y" in config,
            "source kernel lacks ARM64 kexec_file support")
    require(Path("/sys/kernel/kexec_loaded").read_text().strip() == "0",
            "a kexec image is already loaded")

    env = command("grub-editenv", "/boot/grub/grubenv", "list")
    require("saved_entry=spx-known-good" in env.splitlines(),
            "persistent GRUB default is not spx-known-good")
    require(not any(line.startswith("next_entry=") and line != "next_entry="
                    for line in env.splitlines()), "another GRUB boot is queued")
    require("BootNext:" not in command("efibootmgr"), "EFI BootNext is set")

    watchdog = Path("/sys/class/watchdog/watchdog0")
    require(watchdog.is_dir(), "watchdog0 is absent; use the known-good WDT guardian DTB")
    identity_file = watchdog / "identity"
    if identity_file.exists():
        identity = identity_file.read_text().strip().lower()
    else:
        identity = (watchdog / "device/driver").resolve().name.lower()
    require("qcom" in identity, "watchdog0 is not the Qualcomm watchdog")
    compatibles = set(Path("/proc/device-tree/soc@0/watchdog@17c10000/compatible")
                      .read_bytes().rstrip(b"\0").decode().split("\0"))
    require(GUARDIAN_WATCHDOG_COMPATIBLE <= compatibles,
            "live watchdog node is not the audited known-good node")
    require(config_value("RuntimeWatchdogUSec") == "30s",
            "RuntimeWatchdogSec must be 30s")
    require(config_value("KExecWatchdogUSec") == "30s",
            "KExecWatchdogSec must be 30s")

    # Repeat the reboot-hygiene observations last so a concurrent transition
    # cannot turn a pass into authorization for a different boot.
    require(Path("/proc/sys/kernel/random/boot_id").read_text().strip() == boot_id,
            "boot changed during checks; harvest it instead of retrying")
    return {"boot_id": boot_id, "boot_start": boot_start,
            "uptime_seconds": age, "watchdog": identity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--offline", action="store_true",
                        help="validate target artifacts without a live guardian")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = {"target": validate_manifest(manifest)}
    if not args.offline:
        result["guardian"] = validate_live_guardian()
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.offline:
        print("READ-ONLY OFFLINE PASS: artifacts only; no kexec was loaded")
    else:
        print("READ-ONLY GUARD PASS: no kexec was loaded or executed")


if __name__ == "__main__":
    main()
