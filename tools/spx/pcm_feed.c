// SPDX-License-Identifier: GPL-2.0
/*
 * spx-pcm-feed: low-latency stdin -> ALSA feeder for the SPX retained Q6ASM
 * playback PCM.
 *
 * The retained session cannot be re-prepared after an XRUN and reports its
 * position in whole periods. This feeder therefore never lets the PCM stop
 * (stop_threshold = boundary, played area auto-silenced), keeps the ring
 * fill inside a small window by inserting silence or dropping input, and
 * supplies silence whenever stdin has nothing. Input is 48 kHz S16_LE stereo.
 *
 * usage: spx-pcm-feed DEVICE PERIOD_FRAMES PERIODS [STATS_FILE]
 * build: gcc -O2 -o /usr/local/lib/spx/spx-pcm-feed pcm_feed.c -lasound
 */
#define _GNU_SOURCE
#include <alsa/asoundlib.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define FRAME 4

static volatile sig_atomic_t stop;

static void on_signal(int sig)
{
	(void)sig;
	stop = 1;
}

static double now(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

#define CHECK(call) do { \
	int _e = (call); \
	if (_e < 0) { \
		fprintf(stderr, "spx-pcm-feed: %s: %s\n", #call, snd_strerror(_e)); \
		return 1; \
	} \
} while (0)

static int put(snd_pcm_t *pcm, const char *data, long frames)
{
	while (frames > 0) {
		snd_pcm_sframes_t n = snd_pcm_writei(pcm, data, frames);

		if (n == -EAGAIN)
			continue;
		if (n < 0) {
			fprintf(stderr, "spx-pcm-feed: write: %s\n", snd_strerror(n));
			return -1;
		}
		data += n * FRAME;
		frames -= n;
	}
	return 0;
}

int main(int argc, char **argv)
{
	snd_pcm_hw_params_t *hw;
	snd_pcm_sw_params_t *sw;
	snd_pcm_uframes_t period, buffer, boundary;
	unsigned long long in_frames = 0, inserted = 0, dropped = 0;
	unsigned long underruns = 0, corrections = 0;
	long low, high, max_jump, last_avail = -1, fill_min = 1 << 30, fill_max = -1;
	double last_jump = 0, max_gap = 0, last_stats, window_start;
	long window_jump = 0;
	static char silence[65536], input[16384];
	size_t held = 0;
	struct sched_param rt = { .sched_priority = 20 };
	struct sigaction sa = { .sa_handler = on_signal };
	snd_pcm_t *pcm;
	int periods;

	if (argc < 4) {
		fprintf(stderr, "usage: %s DEVICE PERIOD_FRAMES PERIODS [STATS_FILE]\n", argv[0]);
		return 2;
	}
	period = strtoul(argv[2], NULL, 10);
	periods = atoi(argv[3]);
	if (period < 48 || period > 4096 || periods < 4 || periods > 8) {
		fprintf(stderr, "spx-pcm-feed: unsupported geometry\n");
		return 2;
	}
	buffer = period * periods;

	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);
	sched_setscheduler(0, SCHED_FIFO, &rt);	/* Best effort. */
	mlockall(MCL_CURRENT | MCL_FUTURE);

	CHECK(snd_pcm_open(&pcm, argv[1], SND_PCM_STREAM_PLAYBACK, 0));
	snd_pcm_hw_params_alloca(&hw);
	CHECK(snd_pcm_hw_params_any(pcm, hw));
	CHECK(snd_pcm_hw_params_set_access(pcm, hw, SND_PCM_ACCESS_RW_INTERLEAVED));
	CHECK(snd_pcm_hw_params_set_format(pcm, hw, SND_PCM_FORMAT_S16_LE));
	CHECK(snd_pcm_hw_params_set_channels(pcm, hw, 2));
	CHECK(snd_pcm_hw_params_set_rate(pcm, hw, 48000, 0));
	CHECK(snd_pcm_hw_params_set_period_size(pcm, hw, period, 0));
	CHECK(snd_pcm_hw_params_set_buffer_size(pcm, hw, buffer));
	CHECK(snd_pcm_hw_params(pcm, hw));

	snd_pcm_sw_params_alloca(&sw);
	CHECK(snd_pcm_sw_params_current(pcm, sw));
	CHECK(snd_pcm_sw_params_get_boundary(sw, &boundary));
	CHECK(snd_pcm_sw_params_set_start_threshold(pcm, sw, 1));
	CHECK(snd_pcm_sw_params_set_stop_threshold(pcm, sw, boundary));
	CHECK(snd_pcm_sw_params_set_silence_threshold(pcm, sw, 0));
	CHECK(snd_pcm_sw_params_set_silence_size(pcm, sw, boundary));
	CHECK(snd_pcm_sw_params_set_avail_min(pcm, sw, period));
	CHECK(snd_pcm_sw_params(pcm, sw));
	/* hw_params already prepared the PCM; the retained session forbids a second prepare. */

	/*
	 * The driver hands [hw_ptr, hw_ptr + jump) to the DSP when hw_ptr
	 * advances, so one full jump must remain queued after every advance.
	 */
	max_jump = period;
	low = 2 * max_jump + period / 2;
	high = low + 3 * period;
	if (put(pcm, silence, low))
		return 1;

	fcntl(STDIN_FILENO, F_SETFL, fcntl(STDIN_FILENO, F_GETFL) | O_NONBLOCK);
	last_stats = last_jump = window_start = now();

	while (!stop) {
		struct pollfd pfd = { .fd = STDIN_FILENO, .events = POLLIN };
		snd_pcm_sframes_t avail;
		long fill, frames = 0;
		double t;
		ssize_t n;

		poll(&pfd, 1, 2);
		avail = snd_pcm_avail(pcm);
		if (avail < 0) {
			fprintf(stderr, "spx-pcm-feed: avail: %s\n", snd_strerror(avail));
			return 1;
		}
		t = now();
		fill = (long)buffer - avail;
		if (fill < 0) {
			/* Late: skip the already played gap instead of writing into it. */
			underruns++;
			snd_pcm_forward(pcm, -fill);
			avail = snd_pcm_avail(pcm);
			fill = (long)buffer - avail;
		} else if (last_avail >= 0 && avail > last_avail) {
			long jump = avail - last_avail;

			if (t - last_jump > max_gap)
				max_gap = t - last_jump;
			last_jump = t;
			if (jump > window_jump)
				window_jump = jump;
			/* Grow at once for a burst; relax after 30 s without one. */
			if (window_jump > max_jump || t - window_start >= 30) {
				if (window_jump > max_jump || window_jump >= (long)period)
					max_jump = window_jump;
				if (max_jump > (long)buffer / 2)
					max_jump = buffer / 2;
				low = 2 * max_jump + period / 2;
				high = low + 3 * period;
				if (high > (long)buffer - (long)period)
					high = buffer - period;
				if (low > high - (long)period)
					low = high - period;
				window_jump = 0;
				window_start = t;
			}
		}

		if (pfd.revents & (POLLIN | POLLHUP)) {
			n = read(STDIN_FILENO, input + held, sizeof(input) - held);
			if (n == 0)
				break;
			if (n > 0) {
				held += n;
				frames = held / FRAME;
			}
		}
		if (frames) {
			int silent = 1;
			long i;

			for (i = 0; i < frames * FRAME; i++)
				if (input[i]) {
					silent = 0;
					break;
				}
			in_frames += frames;
			if (fill + frames > high ||
			    (silent && fill > low + (long)period)) {
				/* Too much queued: discard, preferably inaudible input. */
				dropped += frames;
				corrections++;
			} else {
				if (put(pcm, input, frames))
					return 1;
				fill += frames;
			}
			memmove(input, input + frames * FRAME, held - frames * FRAME);
			held -= frames * FRAME;
		}
		if (fill < low) {
			long pad = low - fill;

			if (pad > (long)sizeof(silence) / FRAME)
				pad = sizeof(silence) / FRAME;
			if (put(pcm, silence, pad))
				return 1;
			inserted += pad;
			fill += pad;
		}
		if (fill < fill_min)
			fill_min = fill;
		if (fill > fill_max)
			fill_max = fill;
		last_avail = (long)buffer - fill;

		if (argc > 4 && t - last_stats >= 2) {
			char path[4096];
			FILE *f;

			snprintf(path, sizeof(path), "%s.tmp", argv[4]);
			f = fopen(path, "w");
			if (f) {
				fprintf(f, "{\"period\": %lu, \"buffer\": %lu, \"low\": %ld, "
					"\"high\": %ld, \"max_jump\": %ld, \"max_jump_gap_ms\": %.1f, "
					"\"fill_min\": %ld, \"fill_max\": %ld, \"in_frames\": %llu, "
					"\"inserted_frames\": %llu, \"dropped_frames\": %llu, "
					"\"corrections\": %lu, \"underruns\": %lu}\n",
					period, buffer, low, high, max_jump, max_gap * 1000,
					fill_min, fill_max, in_frames, inserted, dropped,
					corrections, underruns);
				fclose(f);
				rename(path, argv[4]);
			}
			last_stats = t;
			fill_min = 1 << 30;
			fill_max = -1;
			max_gap = 0;
		}
	}
	snd_pcm_drop(pcm);
	snd_pcm_close(pcm);
	return 0;
}
