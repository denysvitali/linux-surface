import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("hw_validation", Path(__file__).with_name("hw_validation.py"))
hw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hw)


class ValidationTests(unittest.TestCase):
    def test_frozen_requirements(self):
        rows = hw.checklist((hw.ROOT / "PORT-CHECKLIST.md").read_text())
        self.assertEqual(len(rows), 47)
        self.assertEqual({b["id"] for b in rows if b["closed"]}, {"B02", "B03", "D02"})
        self.assertIn("five cold boots", rows[0]["acceptance"])
        self.assertNotIn("Notes, not acceptance", str(rows))
        with self.assertRaises(ValueError):
            hw.checklist("")

    def test_safe_probes_and_unknown(self):
        def fail():
            raise PermissionError("denied")
        checks = [dict(id=i, tier="passive", box="B01", title=i,
                       fn=fail if i == "plat.model" else lambda: ("PASS", "00:11:22:33:44:55"))
                  for i in sorted(hw.SAFE)]
        def forbidden():
            self.fail("unsafe probe executed")
        checks += [dict(id="cam.apps", tier="passive", fn=forbidden),
                   dict(id="cam.frames", tier="camera", fn=forbidden)]
        probes = hw.probe(SimpleNamespace(CHECKS=checks))
        self.assertEqual(len(probes), len(hw.SAFE))
        self.assertIn("unknown", {p["state"] for p in probes})
        self.assertNotIn("00:11:22:33:44:55", str(probes))

    def test_observations_never_close_boxes(self):
        boxes = hw.checklist((hw.ROOT / "PORT-CHECKLIST.md").read_text())
        report = hw.assemble(boxes, [dict(id="test", boxes=["B01"], title="test",
                             state="observed", detail="present")],
                             dict(kernel="fixture", boot_id="fixture", date="fixture"))
        self.assertEqual(report["closed"], 3)
        self.assertIn("### B01", hw.markdown(report))
        self.assertIn("### F04", hw.markdown(report))
        self.assertIn("none; not automatically checked", hw.markdown(report))


if __name__ == "__main__":
    unittest.main()
