#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One ephemeral SPX TPM ECDSA signature; no provisioning or persistent writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
TOOLS = Path('/var/tmp/spx-tpm2-tools-5.8/usr/bin')
COMMANDS = {0x131, 0x15d, 0x161, 0x162, 0x165, 0x173}
ATTRIBUTES = 'fixedtpm|fixedparent|sensitivedataorigin|userwithauth|noda|sign'
BUDGET = 90
CLEANUP_BUDGET = 25
RETURN_RESERVE = 150
LOG_LIMIT = 65536


def clean_environment(work):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TPM2', 'TSS2', 'OPENSSL'))}
    env.update(PATH='/usr/bin:/bin', LC_ALL='C', HOME=str(work), OPENSSL_CONF='/dev/null')
    return env


def fd_owners(proc=Path('/proc')):
    owners = []
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    target = os.readlink(fd)
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if re.fullmatch(r'/dev/tpm(?:rm)?[0-9]+', target):
                    owners.append(dict(pid=int(process.name), fd=fd.name, device=target))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return owners


def raw_snapshot():
    """Runs only as a timed child: raw handles include every RM client's objects."""
    sys.path.insert(0, str(HERE))
    import check
    with open('/dev/tpm0', 'r+b', buffering=0) as device:
        def cap(kind, first, count, width):
            data = check.command(device, 0x17a, struct.pack('>III', kind, first, count))
            assert len(data) >= 9
            more, returned, entries = struct.unpack('>BII', data[:9])
            assert more == 0 and returned == kind and entries <= count, 'incomplete TPM capability'
            assert len(data) == 9 + entries * width, 'TPM capability length mismatch'
            return data[9:]
        inventory = {}
        for name, first in [('transient', 0x80000000), ('persistent', 0x81000000), ('nv', 0x01000000)]:
            data = cap(1, first, 64, 4)
            values = [v[0] for v in struct.iter_unpack('>I', data)]
            assert all(v >> 24 == first >> 24 for v in values)
            inventory[name] = sorted(values)
        algorithms = [v[0] for v in struct.iter_unpack('>HI', cap(0, 0, 128, 6))]
        commands = [v[0] & 0xffff for v in struct.iter_unpack('>I', cap(2, 0, 512, 4))]
        curves = [v[0] for v in struct.iter_unpack('>H', cap(8, 0, 64, 2))]
        public = check.check(device)
    return dict(inventory=inventory, algorithms=algorithms, commands=commands,
                curves=curves, public=public)


def capabilities_proven(snapshot):
    public = snapshot['public']
    assert public['complete'] and public['manufacturer'] == 'QCOM', 'SPX Qualcomm TPM public check required'
    assert {0xb, 0x23, 0x18} <= set(snapshot['algorithms']), 'SHA256/ECC/ECDSA missing'
    assert 3 in snapshot['curves'], 'NIST P256 missing'
    assert COMMANDS <= set(snapshot['commands']), 'required transient signing commands missing'


def unchanged(before, after):
    return (before['inventory'] == after['inventory'] and
            all(before['public'][k] == after['public'][k]
                for k in ('pcr0_algorithm', 'pcr0', 'pcr_update')))


def verify_result(code, text, *, tampered=False):
    if tampered:
        assert code == 1 and re.search(r'^Verification failure\s*$', text, re.I | re.M), 'tampered signature was not explicitly rejected'
    else:
        assert code == 0 and re.search(r'^Verified OK\s*$', text, re.M), 'original signature verification failed'


class Live:
    def __init__(self, output, attempt, release, tools=TOOLS):
        self.output, self.attempt, self.release = Path(output), attempt, release
        self.tools = Path(tools).resolve()
        self.work = None
        self.deadline = time.monotonic() + BUDGET
        self.commands = []

    def command(self, label, argv, *, allow_failure=False):
        remaining = self.deadline - time.monotonic()
        assert remaining > 0, 'TPM signing budget exhausted'
        log = self.output / (label + '.log')
        def limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (LOG_LIMIT, LOG_LIMIT))
        with log.open('xb') as stream:
            child = subprocess.Popen(list(map(str, argv)), cwd=self.work, env=clean_environment(self.work),
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=limits)
            try:
                code = child.wait(timeout=min(15, remaining))
            finally:
                # Reap even on timeout/interruption, including any private descendants.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=2)
        text = log.read_text(errors='replace')
        self.commands.append(dict(label=label, argv=list(map(str, argv)), returncode=code))
        assert log.stat().st_size < LOG_LIMIT, 'command log exceeded bound'
        if not allow_failure:
            assert code == 0, label + ' failed'
        return code, text

    def tpm(self, label, tool, *args):
        return self.command(label, [self.tools / ('tpm2_' + tool), '-T', 'device:/dev/tpmrm0', *args])

    def snapshot(self, label):
        path = self.work / (label + '.json')
        self.command(label, [sys.executable, '-B', str(HERE / 'sign.py'), '--snapshot', str(path)])
        return json.loads(path.read_text())

    def gate(self):
        assert os.geteuid() == 0 and os.uname().release == self.release
        assert re.fullmatch(r'[0-9]{8}[a-z0-9]+', self.attempt)
        words = Path('/proc/cmdline').read_text().split()
        assert [w for w in words if w.startswith('spx_attempt=')] == ['spx_attempt=' + self.attempt]
        assert 'spx_boot=mainline-functional' in words
        assert Path('/sys/firmware/devicetree/base/model').read_bytes().rstrip(b'\0').startswith(b'Microsoft Surface Pro X')
        for node in ('/dev/tpm0', '/dev/tpmrm0'):
            assert stat.S_ISCHR(Path(node).stat().st_mode)
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        baseline = json.loads((self.output.parent / 'functional.json').read_text())
        assert baseline.get('complete') is True and baseline['boot_id'] == boot and baseline['release'] == self.release
        assert not fd_owners(), 'another TPM client has an open device'
        # These commands read systemd, not the TPM; execute before claiming the test.
        active = subprocess.check_output(['systemctl', 'is-active', 'spx-trial-return@' + self.attempt + '.timer'], text=True, timeout=5).strip()
        assert active == 'active'
        raw = subprocess.check_output(['busctl', 'get-property', 'org.freedesktop.systemd1',
            '/org/freedesktop/systemd1/unit/spx_2dtrial_2dreturn_40' + self.attempt + '_2etimer',
            'org.freedesktop.systemd1.Timer', 'NextElapseUSecMonotonic'], text=True, timeout=5).split()
        assert raw[0] == 't' and int(raw[1]) / 1e6 - time.monotonic() >= RETURN_RESERVE, '150s automatic-return reserve required'
        for name in ('createprimary', 'getcap', 'sign'):
            binary = (self.tools / ('tpm2_' + name)).resolve()
            info = binary.stat()
            assert binary.is_file() and os.access(binary, os.X_OK) and info.st_uid == 0 and not info.st_mode & 0o022
        return boot


def exercise(live):
    result = dict(complete=False, scope='one NULL-hierarchy transient P256 ECDSA SHA256 signature',
                  attempt=live.attempt, release=live.release, secure_boot_acceptance=False)
    before = None
    success = False
    claimed = False
    previous = {}
    try:
        result['boot_id'] = live.gate()  # No TPM action or context before all live prerequisites.
        live.output.mkdir(mode=0o700, exist_ok=False)  # Once consumed, never automatically retry.
        claimed = True
        live.work = Path(tempfile.mkdtemp(prefix='private-', dir=live.output))
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda signum, frame: (_ for _ in ()).throw(RuntimeError('signing interrupted')))
        _, version = live.tpm('version', 'getcap', '--version')
        assert 'version="5.8"' in version, 'private tpm2-tools 5.8 fixture required'
        before = live.snapshot('before')
        result['before'] = before
        for capability in ('algorithms', 'ecc-curves', 'commands'):
            live.tpm('getcap-' + capability, 'getcap', capability)
        capabilities_proven(before)
        assert not fd_owners(), 'TPM client appeared before CreatePrimary'
        live.tpm('createprimary', 'createprimary', '-C', 'n', '-g', 'sha256', '-G', 'ecc256:ecdsa-sha256:null',
                 '-a', ATTRIBUTES, '-R', '-c', 'key.ctx', '-f', 'pem', '-o', 'public.pem')
        message = ('SPX ephemeral signing\nboot=' + result['boot_id'] + '\nattempt=' + live.attempt + '\n').encode() + os.urandom(32)
        (live.work / 'message.bin').write_bytes(message)
        live.command('public-key', ['/usr/bin/openssl', 'pkey', '-pubin', '-in', 'public.pem', '-pubcheck', '-text', '-noout'])
        text = (live.output / 'public-key.log').read_text()
        assert 'Key is valid' in text and 'ASN1 OID: prime256v1' in text and 'NIST CURVE: P-256' in text, 'public key is not P256'
        live.command('digest', ['/usr/bin/openssl', 'dgst', '-sha256', '-binary', '-out', 'digest.bin', 'message.bin'])
        assert (live.work / 'digest.bin').read_bytes() == hashlib.sha256(message).digest(), 'host digest mismatch'
        live.tpm('sign', 'sign', '-c', 'key.ctx', '-g', 'sha256', '-s', 'ecdsa', '-d', '-f', 'plain', '-o', 'signature.der', 'digest.bin')
        verify = ['/usr/bin/openssl', 'dgst', '-sha256', '-verify', 'public.pem', '-signature', 'signature.der']
        verify_result(*live.command('verify-original', [*verify, 'message.bin'], allow_failure=True))
        (live.work / 'tampered.bin').write_bytes(bytes([message[0] ^ 1]) + message[1:])
        verify_result(*live.command('verify-tampered', [*verify, 'tampered.bin'], allow_failure=True), tampered=True)
        result.update(original_verified=True, tampered_rejected=True,
                      challenge_sha256=hashlib.sha256(message).hexdigest())
        success = True
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        # RM device close owns hardware cleanup; never global flush or flush key.ctx.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if live.work is not None:
            try:
                (live.work / 'key.ctx').unlink(missing_ok=True)
                live.deadline = time.monotonic() + CLEANUP_BUDGET
                if before is not None:
                    after = live.snapshot('after')
                    result['after'] = after
                    assert unchanged(before, after), 'TPM handles or PCR0/update changed'
                    assert not fd_owners(), 'TPM client remains open after test'
                    result['inventory_and_pcr_unchanged'] = True
                if success and result.get('inventory_and_pcr_unchanged'):
                    for name in ('message.bin', 'public.pem', 'signature.der'):
                        shutil.copyfile(live.work / name, live.output / name)
                shutil.rmtree(live.work)
                result['private_files_removed'] = True
            except Exception as error:
                result['cleanup_error'] = f'{type(error).__name__}: {error}'
                # Always remove contexts/digests even when the cleanup snapshot fails.
                shutil.rmtree(live.work, ignore_errors=True)
                result['private_files_removed'] = not live.work.exists()
        result['complete'] = bool(success and result.get('inventory_and_pcr_unchanged') and
                                  result.get('private_files_removed') and 'cleanup_error' not in result)
        result['commands'] = live.commands
        if claimed:
            if not result['complete']:
                for name in ('message.bin', 'public.pem', 'signature.der'):
                    (live.output / name).unlink(missing_ok=True)
            (live.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    args.snapshot.write_text(json.dumps(raw_snapshot()))
