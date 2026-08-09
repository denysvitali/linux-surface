/* SPX safe single-shot: open a PCM and PREPARE it (triggers exactly one q6asm
 * ASM_CMD_SHARED_MEM_MAP_REGIONS in the prepare callback), then close. No
 * snd_pcm_writei / no start -> the ADSP registers the mapping but does NOT DMA,
 * so even a wrong mapping can't corrupt memory. set_params() returns the prepare
 * error, so the exit code reflects whether the mem-map was accepted. */
#include <alsa/asoundlib.h>
#include <stdio.h>

int main(int argc, char **argv)
{
	const char *dev = (argc > 1) ? argv[1] : "plughw:0,0";
	snd_pcm_t *pcm;
	int err;

	err = snd_pcm_open(&pcm, dev, SND_PCM_STREAM_PLAYBACK, 0);
	if (err < 0) {
		fprintf(stderr, "open %s: %s\n", dev, snd_strerror(err));
		return 2;
	}
	err = snd_pcm_set_params(pcm, SND_PCM_FORMAT_S16_LE,
				 SND_PCM_ACCESS_RW_INTERLEAVED,
				 2, 48000, 1, 200000);
	if (err < 0) {
		fprintf(stderr, "set_params (prepare/mem-map): %s\n",
			snd_strerror(err));
		snd_pcm_close(pcm);
		return 3;
	}
	fprintf(stderr, "PREPARE OK: mem-map accepted by the ADSP\n");
	snd_pcm_close(pcm);
	return 0;
}
