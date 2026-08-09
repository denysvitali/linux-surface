#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# SPX speaker bring-up: byte-exact AFE SET_PARAM fire sequence (TRACK B,
# firmware-native ELITE/APR path). Synthesized from the real ACDB data
# (Codec_cal/Speaker_cal DPROP 0x113b7 + CDCLUT0 0x15200) and the CAF
# afe_param wire layouts cross-checked against mainline q6afe structs.
#
# It fires the SLIMbus/codec AFE SET_PARAM commands the ADSP needs to bring up
# the WCD9340 SWR master + enumerate the 2x WSA881x amps, the part mainline q6
# does NOT do, while a SLIMBUS_2_RX (0x4004, AFE idx 6) playback stream is live.
# Mainline q6 already does ADM-open + matrix-map + AFE_PORT_DEVICE_START on that
# port; this only adds the missing SLIMbus/codec config.
#
# Each step is fired via scripts/spx-spkr-probe.sh (writes q6afe spx_probe
# debugfs). Between steps it LISTENS so you can tell which one made sound.
#
# SAFETY: SET_PARAM only - NEVER emits an AFE/ADM port STOP/CLOSE (wedges the
# ADSP). Never reads 171c0000+0x2000 or pinmux-pins. rc=0 from the DSP is NOT
# proof of effect (it acks garbage); only AUDIO counts - hence the LISTEN gaps.
#
# Prereq: a LIVE 48k/16-bit stereo stream on SLIMBUS_2_RX (idx 6) for the whole
# run. Start one in another shell BEFORE running this, e.g.:
#     aplay -D plughw:0,0 -r 48000 -f S16_LE -c 2 /usr/share/sounds/.../*.wav
#   (loop a long file or use `while :; do aplay ...; done`), or use
#     ./scripts/spx-run2-pio-full.sh   (brings the SLIMBUS_2_RX path up live).
# The port MUST appear in afe->port_list or every fire returns -ENODEV.

set -u
HERE=$(dirname "$0")
PROBE="$HERE/spx-spkr-probe.sh"
IDX=6                       # SLIMBUS_2_RX enum index (speaker RX, port 0x4004)
LISTEN=${SPX_LISTEN:-6}     # seconds to listen after each fire
ACSP_DIR=${SPX_ACSP_DIR:-/home/dvitali/Documents/drivers/FileRepository/surfaceprox_acsp.inf_arm64_c6cbf7d66dbb0926}
CODEC_ACDB=${SPX_CODEC_CAL:-$ACSP_DIR/Codec_cal.acdb}
CODEC_KEY=${SPX_CODEC_KEY:-0x00015200}
CODEC_BLOB=${SPX_CODEC_BLOB:-/tmp/spx-cdclut0-15200.bin}

[ -x "$PROBE" ] || { echo "missing $PROBE" >&2; exit 1; }
[ -r "$CODEC_ACDB" ] || { echo "missing/read-protected $CODEC_ACDB" >&2; exit 1; }

# ---- AFE module / param ids (from qcauddev/qcadcm RE, CAF apr_audio-v2.h) ----
MOD_CDC_DEV_CFG=0x00010234      # AFE_MODULE_CDC_DEV_CFG
MOD_HW_MAD=0x00010230           # AFE_MODULE_HW_MAD (carries SLAVE_PORT_CFG)

P_CDC_SLIMBUS_SLAVE_CFG=0x00010235   # afe_param_cdc_slimbus_slave_cfg (16B)
P_CDC_REG_PAGE_CFG=0x00010296        # afe_param_cdc_reg_page_cfg (12B)
P_CDC_REG_CFG=0x00010236             # afe_param_cdc_reg_cfg (20B, register data)
P_CDC_REG_CFG_INIT=0x00010237        # commit marker, empty body
P_CDC_REG_CFG_SPX=0x0001029b         # SPX/newer-API CDC reg variant (probe both)
P_SLIMBUS_SLAVE_PORT_CFG=0x00010233  # afe_param_slimbus_slave_port_cfg (32B)
P_SLIMBUS_CONFIG=0x00010212          # AFE_PARAM_ID_SLIMBUS_CONFIG (24B, port cfg)

# ---- byte-exact bodies (LE), see header notes for struct field meaning ----
# afe_param_id_slimbus_cfg (24B): minor=1, dev_id=2(SB_DEVICE_2), bw=16, fmt=0,
#   nch=2, shared_ch_mapping={c0,c1,0,0,0,0,0,0}, sample_rate=48000.
#   c0/c1 = ACDB Speaker_cal DPROP 0x113b7 shared_ch_mapping for SLIMBUS_2_RX.
B_SLIMBUS_CONFIG=010000000200100000000200c0c100000000000080bb0000

# afe_param_cdc_slimbus_slave_cfg (16B): minor=1, enum_lsw=0, enum_msw=0,
#   tx_off=0, rx_off=16. enum_addr is the WCD9340 6-byte SLIM e_addr (runtime,
#   ADSP-owned) - 0 here is a placeholder; see UNCERTAIN note.
B_CDC_SLIMBUS_SLAVE_CFG=01000000000000000000000000001000

# afe_param_cdc_reg_page_cfg (12B): minor=1, enable=1, proc_id=0.
B_CDC_REG_PAGE_CFG=010000000100000000000000

# afe_param_slimbus_slave_port_cfg (32B): minor=1, dev_id=0, pgd_la=0,
#   intf_la=0, bw=16, fmt=0, nch=2, slave_port_mapping={c0,c1,0..}. pgd/intf_la
#   are runtime SLIM logical addresses (ADSP-owned) - 0 placeholder, UNCERTAIN.
B_SLIMBUS_SLAVE_PORT_CFG=01000000000000000000100000000200c000c100000000000000000000000000

fire() {  # label svc(0/1) module param body-hex
	_lbl=$1; _svc=$2; _mod=$3; _par=$4; _body=$5
	echo
	echo "============================================================"
	echo "STEP: $_lbl"
	echo "  $( [ "$_svc" = 1 ] && echo 'SVC V3 0x100fa' || echo 'PORT V3 0x100fc' ) mod=$_mod param=$_par idx=$IDX"
	echo "  body=$_body"
	echo "------------------------------------------------------------"
	if [ "$_svc" = 1 ]; then
		sh "$PROBE" -3 -s -m "$_mod" -p "$_par" -i "$IDX" -x "$_body"
	else
		sh "$PROBE" -3    -m "$_mod" -p "$_par" -i "$IDX" -x "$_body"
	fi
	echo "  >>> LISTEN ${LISTEN}s for speaker output now <<<"
	i=0; while [ "$i" -lt "$LISTEN" ]; do sleep 1; i=$((i+1)); done
}

fire_file() {  # label svc(0/1) module param bin-file
	_lbl=$1; _svc=$2; _mod=$3; _par=$4; _file=$5
	echo
	echo "============================================================"
	echo "STEP: $_lbl"
	echo "  $( [ "$_svc" = 1 ] && echo 'SVC V3 0x100fa' || echo 'PORT V3 0x100fc' ) mod=$_mod param=$_par idx=$IDX"
	echo "  file=$_file size=$(wc -c < "$_file")"
	echo "------------------------------------------------------------"
	if [ "$_svc" = 1 ]; then
		sh "$PROBE" -3 -s -m "$_mod" -p "$_par" -i "$IDX" -f "$_file"
	else
		sh "$PROBE" -3    -m "$_mod" -p "$_par" -i "$IDX" -f "$_file"
	fi
	echo "  >>> LISTEN ${LISTEN}s for speaker output now <<<"
	i=0; while [ "$i" -lt "$LISTEN" ]; do sleep 1; i=$((i+1)); done
}

echo "SPX speaker bring-up sequence on SLIMBUS_2_RX (idx $IDX, port 0x4004)."
echo "Ensure a 48k/S16_LE/2ch stream is ALREADY LIVE on this port."
echo "LISTEN window = ${LISTEN}s/step (override with SPX_LISTEN=N)."
python3 "$HERE/spx-acdb-extract.py" --dump-codec-key "$CODEC_KEY" "$CODEC_ACDB" "$CODEC_BLOB"

# Order rationale: tell the ADSP about the codec SLIM slave first (slave_cfg),
# open the codec register page, then the port-level SLIM channel binding
# (slave_port_cfg + SLIMBUS_CONFIG with the c0/c1 shared channels), so the
# enumerate + channel-map exist before the (already-running) DEVICE_START
# pumps data. CDC_REG_CFG register writes are sent last as they are the most
# likely to be wrong. Live probing showed the SPX stub ADSP rejects these
# bodies via service-level V3 (0x100fa, ADSP error 3) but accepts them via
# port-level V3 (0x100fc), so every step below is port-level.

# 1) Codec SLIMbus slave config (port-level, module CDC_DEV_CFG)
fire "CDC_SLIMBUS_SLAVE_CFG" 0 "$MOD_CDC_DEV_CFG" "$P_CDC_SLIMBUS_SLAVE_CFG" "$B_CDC_SLIMBUS_SLAVE_CFG"

# 2) Codec register page enable (port-level, module CDC_DEV_CFG)
fire "CDC_REG_PAGE_CFG" 0 "$MOD_CDC_DEV_CFG" "$P_CDC_REG_PAGE_CFG" "$B_CDC_REG_PAGE_CFG"

# 3) SLIMbus slave PORT config (PORT-level on 0x4004, module HW_MAD) -
#    binds shared channels c0/c1 to the 2 WSA slave ports.
fire "SLIMBUS_SLAVE_PORT_CFG" 0 "$MOD_HW_MAD" "$P_SLIMBUS_SLAVE_PORT_CFG" "$B_SLIMBUS_SLAVE_PORT_CFG"

# 4) AFE SLIMBUS_CONFIG (PORT-level on 0x4004, RX-codec module 0x15200) -
#    num_ch=2, c0/c1 shared mapping, 48k. This is the authoritative
#    afe_param_id_slimbus_cfg from ACDB DPROP 0x113b7.
fire "SLIMBUS_CONFIG (0x4004 c0/c1 2ch 48k)" 0 0x00015200 "$P_SLIMBUS_CONFIG" "$B_SLIMBUS_CONFIG"

# 5) CDC_REG_CFG from the real Codec_cal CDCLUT0 key 0x15200. The ACDB payload
#    is 0x78 bytes and starts by echoing the codec key; this replaces the old
#    placeholder write, which was not evidence-backed.
fire_file "CDC_REG_CFG (Codec_cal CDCLUT0 0x15200 via 0x10236)" 0 0x00015200 "$P_CDC_REG_CFG" "$CODEC_BLOB"

# 6) Optional adjacent SPX/INIT ids. These returned rc=0 in live V3-port probes,
#    but 0x10236 is the known CDC_REG_CFG id. Enable only while bisecting.
if [ "${SPX_CODEC_VARIANTS:-0}" != 0 ]; then
	fire_file "CDC_REG_CFG_INIT? (Codec_cal CDCLUT0 0x15200 via 0x10237)" 0 0x00015200 "$P_CDC_REG_CFG_INIT" "$CODEC_BLOB"
	fire_file "CDC_REG_CFG_SPX? (Codec_cal CDCLUT0 0x15200 via 0x1029b)" 0 0x00015200 "$P_CDC_REG_CFG_SPX" "$CODEC_BLOB"
fi

# 7) CDC_REG_CFG_INIT commit marker (port-level, empty body). The probe needs a
#    non-empty payload, so we send a single zero byte; the ADSP treats the body
#    as param_size>0 here - if it rejects, this step is informational only.
fire "CDC_REG_CFG_INIT (commit)" 0 0x00015200 "$P_CDC_REG_CFG_INIT" "00"

echo
echo "Sequence complete. If a step produced audio, note its STEP label."
echo "If all silent: the WCD9340 SWR-master enable regs (driver-code resident,"
echo "NOT in ACDB) and/or the runtime SLIM e_addr/LA values are still missing -"
echo "see the agent report for the hard blockers."
