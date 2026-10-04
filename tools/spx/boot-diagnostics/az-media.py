#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Launch bounded AZ media only after normal Venus startup; preserve skipped cases."""
import json
import os
from pathlib import Path
import subprocess

from az_boot_guard import X, RUNTIME, load, trial_identity, sha


def main():
    os.umask(0o077)
    a = load()
    boot = trial_identity(a)
    startup = json.loads((X / 'video-startup/result.json').read_text())
    assert startup['boot_id'] == boot and startup['release'] == a['release']
    ready = any(row['driver'] and row['driver'].endswith('/qcom-venus')
                for row in startup['platform_devices'])
    names = {row['name'] for row in startup['video_nodes']}
    ready = ready and {'qcom-venus-decoder', 'qcom-venus-encoder'} <= names
    if not ready:
        with (X / 'media-not-run.json').open('x') as stream:
            json.dump(dict(boot_id=boot, release=a['release'],
                           reason='Normal Venus startup did not bind both video nodes',
                           video_startup_sha256=sha(X / 'video-startup/result.json'),
                           hardware_codec_used=False, media_acceptance_passed=False), stream, indent=2)
            stream.write('\n')
        os.sync()
        return
    runner = RUNTIME / 'az-media-run.py'
    assert sha(runner) == a['runtime_sha256'][str(runner)]
    subprocess.run(['/usr/bin/python3', str(runner)], check=True, timeout=240)


if __name__ == '__main__':
    main()
