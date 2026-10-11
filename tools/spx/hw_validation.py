#!/usr/bin/env python3
"""Read-only SPX interface inventory and frozen-checklist gap report.

Reuses ../hw-validation/hwv.py, but excludes active tests, camera probing,
raw sensor sampling, thermal sampling and EGL contexts. No acceptance edits.
"""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
# Explicit allowlist: new upstream probes must be inspected before inclusion.
SAFE = frozenset("""plat.model cpu.cores cpu.freq mem.total storage.nvme
storage.space fw.remoteproc fw.services tpm.present tpm.secureboot accel.cdsp
disp.panel disp.backlight gpu.devfreq video.codec in.touch in.pen in.keyboard
in.kbd_backlight in.touchpad in.buttons in.switches aud.card aud.amps aud.desktop
aud.feeder aud.external net.wifi net.bt net.wwan usb.controllers usb.superspeed
usb.typec usb.dp cam.privacy_led sens.als.desktop sens.motion pwr.suspend
pwr.hibernate pwr.idle diag.pstore diag.watchdog diag.kernel_errors diag.taint
diag.units diag.cmdline""".split())


def checklist(text):
    pattern = r"^- \[([ x])\] \*\*([A-Z]\d{2}) — (.*?)\*\*(.*?)(?=^- \[|^## |\Z)"
    rows = []
    for m in re.finditer(pattern, text, re.M | re.S):
        body = m[4].split("*Notes, not acceptance:")[0]
        rows.append(dict(id=m[2], closed=m[1] == "x",
                         acceptance=" ".join((m[3] + body).split())))
    if len(rows) != 47 or len({r["id"] for r in rows}) != 47:
        raise ValueError("expected the frozen 47 unique checklist boxes")
    return rows


def load_suite(path):
    spec = importlib.util.spec_from_file_location("spx_hwv", path)
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    return suite


def probe(suite):
    results = []
    for c in suite.CHECKS:
        if c["id"] not in SAFE or c["tier"] != "passive":
            continue
        try:
            status, detail = c["fn"]()
            state = {"PASS": "observed", "FAIL": "gap suspected", "WARN": "needs investigation",
                     "MANUAL": "needs fixture", "SKIP": "not checked"}.get(status, "unknown")
        except Exception as e:
            state, detail = "unknown", "probe error: %s: %s" % (type(e).__name__, e)
        # Bluetooth suite includes a controller MAC; do not retain it.
        detail = re.sub(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "[address omitted]", detail)
        results.append(dict(id=c["id"], boxes=c["box"].split(","),
                            title=c["title"], state=state, detail=detail))
    missing = SAFE - {r["id"] for r in results}
    if missing:
        raise ValueError("suite is missing expected probes: " + ", ".join(sorted(missing)))
    return results


def assemble(boxes, probes, meta):
    valid = {b["id"] for b in boxes}
    for p in probes:
        if set(p["boxes"]) - valid:
            raise ValueError("probe references an unknown checklist box: " + p["id"])
    for b in boxes:
        b["probes"] = [p["id"] for p in probes if b["id"] in p["boxes"]]
    return dict(meta=meta, closed=sum(b["closed"] for b in boxes), total=len(boxes),
                boxes=boxes, probes=probes)


def markdown(report):
    m = report["meta"]
    lines = [f"boxes closed: {report['closed']} of {report['total']}; newly closed: none.",
             "", "# Surface Pro X hardware gaps", "",
             f"Kernel: `{m['kernel']}`; boot: `{m['boot_id']}`; date: {m['date']}", "",
             "Interface observations are not functional acceptance. A suspected gap can mean",
             "missing support, an unloaded driver, an absent accessory, access restrictions,",
             "or a wrong probe assumption. Missing Linux nodes do not prove missing hardware.",
             "No sound, media capture, raw sensor reads, load, sleep or reboot is performed.", "",
             "## Interface findings needing investigation", "",
             "| Probe | Boxes | Finding | Detail |", "|---|---|---|---|"]
    def cell(text):
        return str(text).replace("|", "/").replace("\n", " ")
    for p in report["probes"]:
        if p["state"] != "observed":
            lines.append("| " + " | ".join(map(cell, [p["id"], ", ".join(p["boxes"]), p["state"], p["detail"]])) + " |")
    lines += ["", "## Remaining acceptance (exact frozen checklist requirements)", "",
              "Full requirements below remain unmet or unverified, even where interfaces were observed.",
              "Use TODO.md for current findings and blocker order; this tool does not choose work.",
              "Battery testing remains deferred. Physical/lifecycle requirements need real evidence.", ""]
    for b in report["boxes"]:
        if not b["closed"]:
            lines += [f"### {b['id']}", b["acceptance"],
                      "Inventory probes: " + (", ".join(b["probes"]) or "none; not automatically checked"), ""]
    lines += ["## All interface observations", "", "| Probe | State | Detail |", "|---|---|---|"]
    for p in report["probes"]:
        lines.append("| " + " | ".join(map(cell, [p["id"], p["state"], p["detail"]])) + " |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", type=Path, default=ROOT.parent / "hw-validation/hwv.py")
    ap.add_argument("--output", type=Path, help="report basename; writes .md and .json")
    args = ap.parse_args()
    boxes = checklist((ROOT / "PORT-CHECKLIST.md").read_text())
    suite = load_suite(args.suite)
    lock = ROOT / "tools/spx/spx-lock"
    owner = "hw-validation-%d" % os.getpid()
    subprocess.run([str(lock), "acquire", "device", owner], check=True, stdout=subprocess.DEVNULL)
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        probes = probe(suite)
        if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != boot:
            raise RuntimeError("boot changed during inventory; discard mixed evidence")
    finally:
        subprocess.run([str(lock), "release", "device", owner], check=True, stdout=subprocess.DEVNULL)
    report = assemble(boxes, probes, dict(kernel=os.uname().release, boot_id=boot,
                      date=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                      suite=str(args.suite.resolve())))
    text = markdown(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_suffix(".md").write_text(text)
        args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
        print(text.splitlines()[0])
        print("report: " + str(args.output.with_suffix(".md")))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
