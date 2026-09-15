#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Unit tests for the read-only kexec guardian checks."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("kexec-guard.py").read_text()
BUILD_SCRIPT = Path(__file__).with_name("build-kexec-hang.py").read_text()


def arm64_image(magic=0x644D5241, image_size=4096):
    return struct.pack("<IIQQQQQQII", 0, 0, 0x80000, image_size, 2,
                       0, 0, 0, magic, 0) + b"test-release" + bytes(64)


class GuardTests(unittest.TestCase):
    def exercise(self, *, image=None, image_hash=None, cmdline=None,
                 dtb_compatible="qcom,apss-wdt-sc8180x qcom,kpss-wdt"):
        image = arm64_image() if image is None else image
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = {name: base / name for name in ("Image", "initrd", "board.dtb")}
            paths["Image"].write_bytes(image)
            paths["initrd"].write_bytes(b"initrd")
            paths["board.dtb"].write_bytes(b"dtb")
            manifest = {
                "schema": 1,
                "release": "test-release",
                "image": {"path": str(paths["Image"]), "sha256": image_hash or hashlib.sha256(image).hexdigest()},
                "initrd": {"path": str(paths["initrd"]), "sha256": hashlib.sha256(b"initrd").hexdigest()},
                "dtb": {"path": str(paths["board.dtb"]), "sha256": hashlib.sha256(b"dtb").hexdigest()},
                "cmdline": cmdline or "root=/dev/test rootwait panic=10 oops=panic spx_boot=mainline-kexec",
            }
            manifest_path = base / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            def output(argv, **kwargs):
                if argv[0] == "fdtget":
                    return dtb_compatible
                if argv[0] == "lsinitcpio":
                    return "==> Kernel: test-release"
                raise AssertionError(argv)

            message = None
            with patch("subprocess.check_output", side_effect=output), \
                 patch("sys.argv", ["kexec-guard.py", "--offline", str(manifest_path)]):
                try:
                    exec(compile(SCRIPT, "kexec-guard.py", "exec"), {"__name__": "__main__"})
                except SystemExit as exc:
                    message = str(exc)
            return message

    def test_valid_offline_manifest_passes(self):
        self.assertIsNone(self.exercise())

    def test_hash_mismatch_is_blocked(self):
        self.assertIn("hash mismatch", self.exercise(image_hash="0" * 64))

    def test_non_arm64_image_is_blocked(self):
        self.assertIn("ARM64 Image header", self.exercise(image=arm64_image(magic=0)))

    def test_zero_image_size_is_blocked(self):
        self.assertIn("zero image_size", self.exercise(image=arm64_image(image_size=0)))

    def test_watchdogless_dtb_is_blocked(self):
        self.assertIn("watchdog compatibles", self.exercise(dtb_compatible="qcom,kpss-wdt"))

    def test_missing_recovery_cmdline_is_blocked(self):
        self.assertIn("target command line lacks", self.exercise(cmdline="root=/dev/test rootwait"))

    def test_hang_payload_header_and_instructions(self):
        namespace = {"__name__": "not_main"}
        exec(compile(BUILD_SCRIPT, "build-kexec-hang.py", "exec"), namespace)
        payload = namespace["PAYLOAD"]
        self.assertEqual(len(payload), 4096)
        fields = struct.unpack("<IIQQQQQQII", payload[:64])
        self.assertEqual(fields[:2], (0x14000010, 0xD503201F))
        self.assertEqual(fields[2:5], (0x80000, 4096, 2))
        self.assertEqual(fields[8], 0x644D5241)
        self.assertEqual(struct.unpack("<III", payload[64:76]),
                         (0xD5034FDF, 0xD503205F, 0x17FFFFFF))
        self.assertEqual(set(payload[76:]), {0})


if __name__ == "__main__":
    unittest.main()
