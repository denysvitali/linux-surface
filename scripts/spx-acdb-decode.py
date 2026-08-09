#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
#
# Surface Pro X (sc8180x) ACDB speaker recipe decoder.
#
# Parses the QCMSNDDB ACDB files shipped in the Windows driverstore and
# decodes them into a structured JSON the parent agent can hand to a
# downstream agent that re-writes the values from APPS over SLIMbus.
#
# Specifically extracts:
#   - Codec_cal CDCLUT0 : 29 structured CDC reg cfg blobs (one per codec
#                         device/channel key id1). Each blob carries the
#                         codec-internal reg writes (page selects, reg/
#                         value pairs) needed to bring up that subsystem.
#                         Key for speakers: id1=0x15200 (SPEAKER_PHONE_SPKR_STEREO).
#   - Codec_cal CPROPLUT : the friendly name of each id1 (UTF-16LE).
#   - Speaker_cal DPROP  : per-device (dev 0x45) AFE/SLIMbus/copp properties
#                         at 48kHz. 0x113b7 = SLIMBUS_2_RX port cfg,
#                         0x113af = topology marker 0x10000001,
#                         0x113ad = ADM routing matrix, 0x113b6 = AFE-param
#                         CDC reg cfg list, 0x113b8 = endpoint name.
#
# Output: JSON to stdout (and /tmp/spx-acdb-decoded.json).

import struct, sys, os, json

DEF_DIR = ("/home/dvitali/Documents/drivers/FileRepository/"
           "surfaceprox_acsp.inf_arm64_c6cbf7d66dbb0926")

SPEAKER_DEV = 0x45
SR_48K = 0xBB80

# AFE param ids (legacy ELITE) for cross-reference.
AFE_PARAM = {
    0x00010102: "RX_CDC_DEV",        # codec-side id 1, earout
    0x00011103: "RX_CDC_DEV_STEREO", # headset
    0x00011106: "RX_CDC_DEV_MONO",   # headset mono
    0x00011107: "RX_CDC_DEV_MONO_R", # headset mono right
    0x00013100: "LINEOUT_1",         # line out
    0x00013101: "LINEOUT_2",
    0x00015100: "SPKR_MONO",         # speaker phone mono
    0x00015101: "SPKR_2_MONO",       # dual speaker mono
    0x00015200: "SPKR_STEREO",       # dual speaker STEREO (== SPX WSA881x)
    0x00020100: "ADC_1",
    0x00020101: "ADC_2",
    0x00020102: "ADC_3",
    0x00021100: "DMIC_1",
    0x00021101: "DMIC_2",
    0x00021102: "DMIC_3",
    0x00021103: "DMIC_4",
    0x00021104: "DMIC_5",
    0x00021105: "DMIC_6",
    0x00021203: "DMIC_3_5_STEREO",
    0x00021204: "DMIC_4_6_STEREO",
    0x00021205: "DMIC_1_3_STEREO",
    0x00021206: "DMIC_1_4_STEREO",
    0x00021207: "DMIC_2_1_STEREO",
    0x00021405: "DMIC_1_3_5_4_QUAD",
    0x00021406: "DMIC_3_5_6_4_QUAD",
    0x00022200: "DMIC_4_6_LISTEN",
    0x00022201: "DMIC_3_5_LISTEN",
    0x00022202: "DMIC_2_1_LISTEN",
    0x00022203: "DMIC_2_LISTEN",
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
        self.chunks = {}
        pos = 0x20
        while pos < len(b):
            tag = b[pos:pos + 8].decode("latin1").rstrip()
            ln = u32(b, pos + 8)
            self.chunks[tag] = (pos + 12, ln)
            pos += 12 + ln
        ds = self.chunks.get("DATAPOOL")
        self.dp_base = ds[0] if ds else None

    def chunk(self, tag):
        st, ln = self.chunks[tag]
        return self.b[st:st + ln]

    def lut(self, tag):
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

    def string_blob(self, dp_off):
        """CPROPLUT/DPROP-name blob: u32 nbytes of UTF-16LE then payload."""
        o = self.dp_base + dp_off
        nbytes = u32(self.b, o)
        body = self.b[o + 4:o + 4 + nbytes]
        try:
            return body.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            return body.hex()

    def blob(self, dp_off):
        """Raw bytes at dp_off (used when the blob is opaque/structured)."""
        o = self.dp_base + dp_off
        # First u32 is the length of the structured payload that follows.
        nbytes = u32(self.b, o)
        return self.b[o + 4:o + 4 + nbytes]

    def blob_u32s(self, dp_off):
        return list(struct.unpack_from(f"<{len(self.blob(dp_off))//4}I",
                                       self.blob(dp_off)))


def decode_cdclut0(a):
    """Codec_cal CDCLUT0  -> list of CDC reg cfg blobs.

    Each blob is laid out as a sequence of u32 register-write records of
    the form  (reg_addr_u32, value_u32), with sparse zero-padding. We
    classify each non-zero u32 into:

      * PAGE_SELECT  : 0x00PP0000  (page PP, offset=0)
      * REG_WRITE    : reg_addr_hi<<16 | reg_addr_lo, value_hi<<16 | value_lo
                       packed as a SINGLE u32  (0xVVVVAAAA little-endian).
                       This is the MSM "reg-writes-as-pairs" packing used by
                       CDC_REG_CFG and CDC_REG_CFG_INIT payloads.
      * SCALAR       : not a packed pair (e.g. count, mask, status)

    The byte-exact body_hex is preserved so callers can replay the blob
    verbatim into the codec regmap if needed.
    """
    out = []
    cnt, _, recs = a.lut("CDCLUT0")
    for i, (id1, id2, dp_off) in enumerate(recs):
        body = a.blob(dp_off)
        if len(body) < 8:
            continue
        body_u32s = [struct.unpack_from("<I", body, j * 4)[0]
                     for j in range(len(body) // 4)]
        page_selects = []
        reg_writes = []
        scalars = []
        for j, v in enumerate(body_u32s):
            if v == 0:
                continue
            hi = (v >> 16) & 0xFFFF
            lo = v & 0xFFFF
            # page select: 0x00PP0000  (page = hi, offset = 0)
            if hi in (0x0084, 0x0184, 0x0001, 0x0080, 0x0100, 0x0000) and lo == 0:
                page_selects.append({
                    "idx": j,
                    "page": f"0x{hi:04x}",
                    "raw": f"0x{v:08x}",
                })
            # packed reg/value pair: (reg_addr<<16 | val) le
            elif hi != 0 and lo != 0 and hi < 0x200 and lo < 0x200:
                reg_writes.append({
                    "idx": j,
                    "reg": f"0x{lo:04x}",
                    "value": f"0x{hi:04x}",
                    "raw": f"0x{v:08x}",
                })
            elif hi != 0 and lo != 0 and hi > lo and hi < 0x10000:
                reg_writes.append({
                    "idx": j,
                    "reg": f"0x{lo:04x}",
                    "value": f"0x{hi:04x}",
                    "raw": f"0x{v:08x}",
                })
            else:
                scalars.append({"idx": j, "value": f"0x{v:08x}"})
        out.append({
            "index": i,
            "id1": f"0x{id1:08x}",
            "id2": f"0x{id2:08x}",
            "dp_off": f"0x{dp_off:04x}",
            "size_bytes": len(body),
            "body_hex": body.hex(),
            "body_u32_count": len(body_u32s),
            "body_u32_nonzero": [f"0x{v:08x}" for v in body_u32s if v],
            "page_selects": page_selects,
            "reg_writes": reg_writes,
            "scalars": scalars,
            "afe_param_name": AFE_PARAM.get(id1, f"CDC_{id1:08x}"),
        })
    return out


def decode_cproplut(a):
    out = []
    cnt, _, recs = a.lut("CPROPLUT")
    for i, (id1, id2, dp_off) in enumerate(recs):
        s = a.string_blob(dp_off)
        out.append({
            "index": i,
            "id1": f"0x{id1:08x}",
            "id2": f"0x{id2:08x}",
            "dp_off": f"0x{dp_off:04x}",
            "name": s,
            "afe_param_name": AFE_PARAM.get(id1, f"CDC_{id1:08x}"),
        })
    return out


def decode_speaker_dprop(a, dev=SPEAKER_DEV, sr=SR_48K):
    """For each (dev=0x45) entry in DPROPLUT, return id2 + body.

    Some DPROP entries are u16 strings (property names); others are
    structured u32 records.  A DPROP entry is a string iff the
    property id is in a known set (we know 0x113b8 = endpoint name).
    Everything else is decoded as u32 list.
    """
    KNOWN_STRING_PROPS = {0x113b8}
    out = []
    cnt, _, recs = a.lut("DPROPLUT")
    for i, (dev_id, prop_id, dp_off) in enumerate(recs):
        if dev_id != dev:
            continue
        body = a.blob(dp_off)
        if prop_id in KNOWN_STRING_PROPS:
            s = a.string_blob(dp_off)
            out.append({
                "index": i,
                "dev": f"0x{dev_id:08x}",
                "prop_id": f"0x{prop_id:08x}",
                "dp_off": f"0x{dp_off:04x}",
                "kind": "string",
                "value": s,
                "body_hex": body.hex(),
            })
        else:
            u32s = list(struct.unpack_from(f"<{len(body)//4}I", body))
            out.append({
                "index": i,
                "dev": f"0x{dev_id:08x}",
                "prop_id": f"0x{prop_id:08x}",
                "dp_off": f"0x{dp_off:04x}",
                "kind": "u32s",
                "u32s": [f"0x{v:08x}" for v in u32s],
                "body_hex": body.hex(),
            })
    return out


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else DEF_DIR
    codec = Acdb(os.path.join(d, "Codec_cal.acdb"))
    spkr = Acdb(os.path.join(d, "Speaker_cal.acdb"))
    out = {
        "input_dir": d,
        "codec_cal": {
            "subtype": codec.subtype,
            "size": len(codec.b),
            "chunks": list(codec.chunks.keys()),
            "datapool_off": f"0x{codec.dp_base:x}",
            "cdclut0": decode_cdclut0(codec),
            "cproplut": decode_cproplut(codec),
        },
        "speaker_cal": {
            "subtype": spkr.subtype,
            "size": len(spkr.b),
            "chunks": list(spkr.chunks.keys()),
            "datapool_off": f"0x{spkr.dp_base:x}",
            "dprop_dev_45": decode_speaker_dprop(spkr),
        },
        "spx_recipe_summary": {
            "speaker_codec_key": "0x15200",
            "speaker_endpoint_name": "SPEAKER_OUT",
            "afe_port": "0x4004 (SLIMBUS_2_RX)",
            "slim_cfg_key": "0x15200",
            "shared_channels": [192, 193],   # 0xC0, 0xC1
            "topology_marker": "0x10000001",
            "afe_param_cdc_reg_cfg_init": "0x00010237",
            "afe_param_cdc_reg_cfg": "0x00010236",
            "afe_param_cdc_reg_page_cfg": "0x00010296",
            "afe_param_cdc_slimbus_slave_cfg": "0x00010235",
            "afe_param_slimbus_config": "0x00010212",
            "cdc_reg_cfg_init_afe_param_ids_for_dev_45": [
                "0x000112a7",  # from dprop 0x113b6 first u32
                "0x00012a52",  # from dprop 0x113b6 second u32
            ],
            "wsa881x_amps": 2,           # stereo pair
            "swr_master_page": "0x0084", # page 132 = SWR master
        },
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()