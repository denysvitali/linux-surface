#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
#
# Surface Pro X (sc8180x) ACDB speaker-subgraph extractor.
#
# Decodes the Qualcomm QCMSNDDB/ACDB calibration files shipped in the Windows
# driverstore (surfaceprox_acsp.inf package) and extracts the calibration the
# Windows audio driver replays to the ADSP to bring up the WSA881x speaker amps
# (device id 0x45). On SPX the WCD9340 SoundWire master + WSA amps are
# ADSP-owned; the bring-up "recipe" is data in these files, replayed as APR
# AFE_*_SET_PARAM messages over apr_audio_svc (the transport q6afe already uses).
#
# Format (byte-exact, verified by parsing Codec/Global/Speaker_cal end-to-end):
#   header  0x00 u8[8] "QCMSNDDB"; 0x08 8x00; 0x10 u8[4] subtype(CCDB/GCDB/AVDB);
#           0x14 u32 0; 0x18 u32 payload_size(=filesize-0x20); 0x1c u32 dup.
#   chunks  from 0x20: [tag u8[8]][len u32][payload[len]], next=pos+12+len.
#   Codec_cal CDCLUT0/CPROPLUT: [u32 count][rec*12: id1,id2(per-LUT const),dp_off]
#           DATAPOOL blob at dp_off = [u32 total][u32 payload_size][u32 0][payload]
#           payload[0:4] echoes id1. (blob sized by payload_size, NOT by total.)
#   Speaker_cal *LUT0: [u32 count][rec*stride], stride=(chunklen-4)/count.
#           DATAPOOL is sliced RAW (no per-blob header); size = dp_len field, or
#           gap-to-next-offset when dp_len==0 (VSTI/AVOL etc.).
#
# Read-only on the input files unless --dump-codec-key is used.
# Usage:
#   spx-acdb-extract.py [acsp_dir]
#   spx-acdb-extract.py --dump-codec-key <key> <Codec_cal.acdb> <out.bin>

import struct
import sys
import os

DEF_DIR = ("/home/dvitali/Documents/drivers/FileRepository/"
           "surfaceprox_acsp.inf_arm64_c6cbf7d66dbb0926")

SPEAKER_DEV = 0x45
SR_48K = 0xBB80

# Legacy ELITE AFE module/param IDs (from msm apr_audio-v2.h, the model these
# 2019 SC8180X.WP.1.0 / WCD9340.1.0 cal files target). Used only to annotate
# what an extracted blob most likely configures.
AFE_IDS = {
    0x00010102: "?cdc-lut-key 0x010102", 0x00011103: "?cdc-lut-key 0x011103",
    0x00010233: "AFE_PARAM_ID_SLIMBUS_SLAVE_PORT_CFG",
    0x00010235: "AFE_PARAM_ID_CDC_SLIMBUS_SLAVE_CFG",
    0x00010236: "AFE_PARAM_ID_CDC_REG_CFG",
    0x00010237: "AFE_PARAM_ID_CDC_REG_CFG_INIT",
    0x00010296: "AFE_PARAM_ID_CDC_REG_PAGE_CFG",
    0x00010209: "AFE_MODULE_SPEAKER_PROTECTION",
    0x0001020A: "AFE_PARAM_ID_SPKR_PROT_CONFIG",
    0x0001021C: "AFE_MODULE_FB_SPKR_PROT_RX",
    0x0001021D: "AFE_PARAM_ID_FBSP_MODE_RX_CFG",
    0x00010226: "AFE_MODULE_FB_SPKR_PROT_VI_PROC",
    0x00010227: "AFE_PARAM_ID_MODE_VI_PROC_CFG",
    0x0001022A: "AFE_PARAM_ID_SPKR_CALIB_VI_PROC_CFG",
    0x0001022B: "AFE_PARAM_ID_CALIB_RES_CFG",
    0x0001022C: "AFE_PARAM_ID_FEEDBACK_PATH_CFG",
    0x0001025F: "AFE_MODULE_FB_SPKR_PROT_V2_RX",
    0x0001026A: "AFE_MODULE_FB_SPKR_PROT_VI_PROC_V2",
}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


class Acdb:
    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        with open(path, "rb") as f:
            self.b = f.read()
        b = self.b
        assert b[:8] == b"QCMSNDDB", f"{path}: bad magic"
        self.subtype = b[0x10:0x14].decode("latin1")
        self.payload_size = u32(b, 0x18)
        assert self.payload_size == len(b) - 0x20, "payload_size mismatch"
        self.chunks = {}          # tag -> (payload_start, length)
        pos = 0x20
        while pos < len(b):
            tag = b[pos:pos + 8].decode("latin1").rstrip()
            ln = u32(b, pos + 8)
            self.chunks[tag] = (pos + 12, ln)
            pos += 12 + ln
        assert pos == len(b), f"{path}: chunk walk ended at 0x{pos:x} != 0x{len(b):x}"
        ds = self.chunks.get("DATAPOOL")
        self.dp_base = ds[0] if ds else None

    def chunk(self, tag):
        st, ln = self.chunks[tag]
        return self.b[st:st + ln]

    def lut(self, tag):
        """Return (count, stride_bytes, [records-as-u32-tuples])."""
        pl = self.chunk(tag)
        cnt = u32(pl, 0)
        if cnt == 0:
            return 0, 0, []
        stride = (len(pl) - 4) // cnt
        recs = []
        for i in range(cnt):
            off = 4 + i * stride
            recs.append(tuple(u32(pl, off + 4 * j) for j in range(stride // 4)))
        return cnt, stride, recs

    def framed_blob(self, dp_off):
        """Codec_cal DATAPOOL blob: [total][payload_size][rsvd][payload]."""
        o = self.dp_base + dp_off
        total, psize, rsvd = u32(self.b, o), u32(self.b, o + 4), u32(self.b, o + 8)
        return total, psize, rsvd, self.b[o + 12:o + 12 + psize]

    def raw(self, dp_off, ln):
        o = self.dp_base + dp_off
        return self.b[o:o + ln]


def annotate(blob):
    if len(blob) < 4:
        return "(empty)"
    lead = u32(blob, 0)
    if lead in AFE_IDS:
        return f"leads with {AFE_IDS[lead]} (0x{lead:08x})"
    if 0x00010000 <= lead <= 0x0001FFFF:
        return f"leads with AFE-space id 0x{lead:08x}"
    return f"opaque cal data (lead 0x{lead:08x})"


def dump_codec(a):
    print(f"\n===== {a.name} ({a.subtype}) — codec-init / CDC reg cfg blocks =====")
    for tag in ("CDCLUT0", "CPROPLUT"):
        if tag not in a.chunks:
            continue
        cnt, stride, recs = a.lut(tag)
        print(f"  {tag}: {cnt} records (stride {stride}B)")
        for i, (id1, id2, off) in enumerate(recs):
            total, psize, rsvd, blob = a.framed_blob(off)
            echo = "id-match" if (psize and u32(blob, 0) == id1) else "ECHO-MISMATCH"
            note = f"  [{AFE_IDS.get(id1,'')}]" if id1 in AFE_IDS else ""
            print(f"    #{i:02d} id1=0x{id1:08x} id2=0x{id2:08x} dp_off=0x{off:04x} "
                  f"psize=0x{psize:x} {echo}{note}")


def dump_codec_key(path, key, out_path):
    """Write a CDCLUT0 framed DATAPOOL payload for a codec key to out_path."""
    a = Acdb(path)
    cnt, stride, recs = a.lut("CDCLUT0")

    for i, (id1, id2, off) in enumerate(recs):
        if id1 != key:
            continue

        total, psize, rsvd, blob = a.framed_blob(off)
        if rsvd != 0 or len(blob) != psize or (psize >= 4 and u32(blob, 0) != id1):
            raise SystemExit(
                f"{path}: malformed CDCLUT0 key 0x{key:08x} at record {i}"
            )

        with open(out_path, "wb") as f:
            f.write(blob)

        print(f"CDCLUT0 key=0x{key:08x} rec={i} id2=0x{id2:08x} "
              f"dp_off=0x{off:x} total=0x{total:x} payload=0x{psize:x} "
              f"out={out_path}")
        return

    raise SystemExit(f"{path}: CDCLUT0 key 0x{key:08x} not found")


def dump_speaker(a):
    print(f"\n===== {a.name} ({a.subtype}) — device 0x45 speaker subgraph =====")
    # All sub-LUTs that carry per-device calibration. We dump every record and
    # flag those referencing the speaker device / 48k, then slice the datapool.
    for tag in sorted(t for t in a.chunks
                      if t.endswith("LUT0") or t.endswith("LUT")):
        cnt, stride, recs = a.lut(tag)
        if cnt == 0:
            continue
        # find records mentioning the speaker device id or 48k
        hits = [r for r in recs if SPEAKER_DEV in r or SR_48K in r]
        if not hits:
            continue
        # heuristic: the dp_off field is the largest field that lands in-bounds
        # of DATAPOOL across records; collect candidate offsets for gap-sizing.
        dplen = a.chunks["DATAPOOL"][1]
        def is_off(v):
            return 0 < v < dplen
        all_offs = sorted({v for r in recs for v in r if is_off(v)})
        print(f"  {tag}: {cnt} recs (stride {stride}B), {len(hits)} speaker/48k hits")
        for r in hits[:6]:
            cand = [v for v in r if is_off(v)]
            off = cand[-1] if cand else None
            line = "      rec " + " ".join(f"0x{v:x}" for v in r)
            if off is not None:
                nxt = min((o for o in all_offs if o > off), default=None)
                sz = (nxt - off) if nxt else min(0x80, dplen - off)
                blob = a.raw(off, sz)
                line += f"  -> dp@0x{off:x} ~0x{sz:x}B: {annotate(blob)}"
            print(line)


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--dump-codec-key":
        dump_codec_key(sys.argv[3], int(sys.argv[2], 0), sys.argv[4])
        return

    d = sys.argv[1] if len(sys.argv) > 1 else DEF_DIR
    files = {
        "Codec_cal": os.path.join(d, "Codec_cal.acdb"),
        "Global_cal": os.path.join(d, "Global_cal.acdb"),
        "Speaker_cal": os.path.join(d, "Speaker_cal.acdb"),
    }
    acdbs = {}
    for name, path in files.items():
        a = Acdb(path)
        acdbs[name] = a
        print(f"{name}: subtype={a.subtype} size=0x{len(a.b):x} "
              f"chunks={len(a.chunks)} datapool@0x{a.dp_base:x}")
    dump_codec(acdbs["Codec_cal"])
    dump_speaker(acdbs["Speaker_cal"])


if __name__ == "__main__":
    main()
