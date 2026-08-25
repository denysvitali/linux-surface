#!/bin/bash
# SPX objective static/tone tracker (quiet). One iteration = bring the pin2 amp
# up via spx-play-right.sh with a 3 s zero | 5 s 440 Hz | 3 s zero vector at
# low gain, record DMIC1 across it, score with spx-mic-analyze.py, append a
# CSV line: time,uptime,adp,bat%,static_rms,static_dB,tone_rms,f440,ratio,verdict
# Usage: spx-static-track.sh [iterations=1] [interval_s=300]
# LOUD: every amp bring-up plays the residual static at full level regardless of
# SPX_PA_VOLUME. Run ONLY when the user has explicitly asked for that run.
set -u
N=${1:-1}; IV=${2:-300}
cd "$(dirname "$0")/.."
export SPX_PA_VOLUME=${SPX_PA_VOLUME:-4}
GAIN=${SPX_TONE_GAIN:-1.6}
CSV=${SPX_TRACK_CSV:-/var/tmp/spx-static-track.csv}
VEC=/tmp/spx-track-vec.wav
ffmpeg -nostdin -v error -f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
	-f lavfi -i sine=frequency=440:sample_rate=48000:duration=5 \
	-f lavfi -i anullsrc=r=48000:cl=stereo:d=3 \
	-filter_complex "[1:a]volume=$GAIN,pan=stereo|c0=0*c0|c1=c0[t];[0:a][t][2:a]concat=n=3:v=0:a=1[o]" \
	-map '[o]' -c:a pcm_s16le -y "$VEC" || exit 1
[[ -f $CSV ]] || echo "time,uptime,adp,bat,static_rms,static_db,tone_rms,f440,ratio,verdict" > "$CSV"
for ((i=1;i<=N;i++)); do
	N0=$(sudo dmesg | grep -c SPX_PLAY_RIGHT)
	(./scripts/spx-play-right.sh "$VEC" > /tmp/spx-track-play.log 2>&1 &)
	for _ in $(seq 1 60); do [ "$(sudo dmesg | grep -c SPX_PLAY_RIGHT)" -gt "$N0" ] && break; sleep 0.5; done
	W=/var/tmp/spx-track-$(date +%Y%m%d-%H%M%S).wav
	timeout -k 2 14 arecord -q -D plughw:0,1 -f S16_LE -r 48000 -c 1 -d 9 "$W" 2>/dev/null
	A=$(python3 scripts/spx-mic-analyze.py "$W" 0.3)
	echo "$A"
	srms=$(sed -n 's/.*STATIC.*rms= *\([0-9.]*\).*/\1/p' <<<"$A"); sdb=$(sed -n 's/.*static index = \([-+0-9.]*\) dB.*/\1/p' <<<"$A")
	trms=$(sed -n 's/.*tone window *rms= *\([0-9.]*\).*/\1/p' <<<"$A"); f=$(sed -n 's/.*440Hz=\([0-9.]*\) harm.*/\1/p' <<<"$A")
	r=$(sed -n 's/.*ratio=\([0-9.]*\).*/\1/p' <<<"$A"); vd=$(grep -o "TONE DETECTED\|no tone" <<<"$A")
	echo "$(date +%H:%M:%S),$(cut -d. -f1 /proc/uptime),$(cat /sys/class/power_supply/ADP1/online),$(cat /sys/class/power_supply/BAT1/capacity),$srms,$sdb,$trms,$f,$r,$vd" | tee -a "$CSV"
	sleep 12
	(( i < N )) && sleep "$IV"
done
