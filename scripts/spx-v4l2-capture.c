// SPDX-License-Identifier: GPL-2.0
/*
 * Deliberately small V4L2 multiplanar capture harness for the SPX CAMSS tests.
 *
 * v4l2-ctl allocates, queues and starts streaming in one operation.  If
 * STREAMON wedges the SoC, the DMA allocation diagnostics never reach disk.
 * This helper separates those phases, fills both buffers with 0xa5, syncs the
 * allocation evidence, then starts the stream.  A returned buffer therefore
 * tells us whether the VFE wrote zeroes or never touched memory at all.
 */
#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define BUFFER_COUNT 2
#define SENTINEL 0xa5

struct mapped_buffer {
	void *addr;
	size_t length;
};

static int xioctl(int fd, unsigned long request, void *arg)
{
	int ret;

	do {
		ret = ioctl(fd, request, arg);
	} while (ret < 0 && errno == EINTR);

	return ret;
}

static void fail(const char *what)
{
	fprintf(stderr, "CAPTURE_ERROR: %s: %s\n", what, strerror(errno));
	fflush(stderr);
	exit(EXIT_FAILURE);
}

static void write_all(int fd, const uint8_t *data, size_t length)
{
	while (length) {
		ssize_t written = write(fd, data, length);

		if (written < 0) {
			if (errno == EINTR)
				continue;
			fail("write output");
		}
		data += written;
		length -= written;
	}
}

int main(int argc, char **argv)
{
	struct mapped_buffer mapped[BUFFER_COUNT] = { 0 };
	struct v4l2_requestbuffers req = { 0 };
	struct v4l2_format fmt = { 0 };
	enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
	const char *device;
	const char *output;
	const char *fourcc_name = "pBAA";
	uint32_t fourcc = V4L2_PIX_FMT_SBGGR10P;
	unsigned int width;
	unsigned int height;
	unsigned int i;
	int video_fd;
	int output_fd;

	if (argc != 5 && argc != 6) {
		fprintf(stderr,
			"usage: %s DEVICE WIDTH HEIGHT OUTPUT [FOURCC]\n",
			argv[0]);
		return EXIT_FAILURE;
	}

	device = argv[1];
	width = strtoul(argv[2], NULL, 10);
	height = strtoul(argv[3], NULL, 10);
	output = argv[4];
	if (argc == 6) {
		fourcc_name = argv[5];
		if (strlen(fourcc_name) != 4) {
			fprintf(stderr, "FOURCC must contain exactly four characters\n");
			return EXIT_FAILURE;
		}
		fourcc = v4l2_fourcc(fourcc_name[0], fourcc_name[1],
				     fourcc_name[2], fourcc_name[3]);
	}

	video_fd = open(device, O_RDWR | O_NONBLOCK | O_CLOEXEC);
	if (video_fd < 0)
		fail("open video device");

	fmt.type = type;
	fmt.fmt.pix_mp.width = width;
	fmt.fmt.pix_mp.height = height;
	fmt.fmt.pix_mp.pixelformat = fourcc;
	fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;
	if (xioctl(video_fd, VIDIOC_S_FMT, &fmt) < 0)
		fail("VIDIOC_S_FMT");

	printf("CAPTURE_FORMAT: %ux%u fourcc=%c%c%c%c planes=%u stride=%u size=%u\n",
	       fmt.fmt.pix_mp.width, fmt.fmt.pix_mp.height,
	       fmt.fmt.pix_mp.pixelformat & 0xff,
	       (fmt.fmt.pix_mp.pixelformat >> 8) & 0xff,
	       (fmt.fmt.pix_mp.pixelformat >> 16) & 0xff,
	       (fmt.fmt.pix_mp.pixelformat >> 24) & 0xff,
	       fmt.fmt.pix_mp.num_planes,
	       fmt.fmt.pix_mp.plane_fmt[0].bytesperline,
	       fmt.fmt.pix_mp.plane_fmt[0].sizeimage);
	fflush(stdout);

	req.count = BUFFER_COUNT;
	req.type = type;
	req.memory = V4L2_MEMORY_MMAP;
	if (xioctl(video_fd, VIDIOC_REQBUFS, &req) < 0)
		fail("VIDIOC_REQBUFS");
	if (req.count < BUFFER_COUNT) {
		errno = ENOMEM;
		fail("driver returned fewer than two buffers");
	}

	for (i = 0; i < BUFFER_COUNT; i++) {
		struct v4l2_plane planes[VIDEO_MAX_PLANES] = { 0 };
		struct v4l2_buffer buf = { 0 };

		buf.type = type;
		buf.memory = V4L2_MEMORY_MMAP;
		buf.index = i;
		buf.length = VIDEO_MAX_PLANES;
		buf.m.planes = planes;
		if (xioctl(video_fd, VIDIOC_QUERYBUF, &buf) < 0)
			fail("VIDIOC_QUERYBUF");

		mapped[i].length = planes[0].length;
		mapped[i].addr = mmap(NULL, mapped[i].length,
				      PROT_READ | PROT_WRITE, MAP_SHARED,
				      video_fd, planes[0].m.mem_offset);
		if (mapped[i].addr == MAP_FAILED)
			fail("mmap");

		memset(mapped[i].addr, SENTINEL, mapped[i].length);
		if (xioctl(video_fd, VIDIOC_QBUF, &buf) < 0)
			fail("VIDIOC_QBUF");
		printf("CAPTURE_BUFFER: index=%u length=%zu sentinel=0x%02x queued\n",
		       i, mapped[i].length, SENTINEL);
		fflush(stdout);
	}

	/* Give journald and the shell's per-line sync enough time to persist the
	 * kernel's SPX DMA allocation lines before the risky ioctl. */
	printf("CAPTURE_READY: buffers allocated, filled and queued; STREAMON in 5s\n");
	fflush(stdout);
	sync();
	sleep(5);

	printf("CAPTURE_STREAMON: entering ioctl\n");
	fflush(stdout);
	sync();
	if (xioctl(video_fd, VIDIOC_STREAMON, &type) < 0)
		fail("VIDIOC_STREAMON");
	printf("CAPTURE_STREAMON: returned\n");
	fflush(stdout);
	(void)fsync(STDOUT_FILENO);

	output_fd = open(output, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
	if (output_fd < 0)
		fail("open output");

	for (i = 0; i < BUFFER_COUNT; i++) {
		struct v4l2_plane planes[VIDEO_MAX_PLANES] = { 0 };
		struct v4l2_buffer buf = { 0 };
		struct pollfd pfd = { .fd = video_fd, .events = POLLIN };
		size_t zeroes = 0, sentinels = 0, other = 0, used, j;
		uint8_t *bytes;
		int poll_ret;

		do {
			poll_ret = poll(&pfd, 1, 10000);
		} while (poll_ret < 0 && errno == EINTR);
		if (poll_ret == 0) {
			errno = ETIMEDOUT;
			fail("poll waiting for frame");
		}
		if (poll_ret < 0)
			fail("poll");

		buf.type = type;
		buf.memory = V4L2_MEMORY_MMAP;
		buf.length = VIDEO_MAX_PLANES;
		buf.m.planes = planes;
		if (xioctl(video_fd, VIDIOC_DQBUF, &buf) < 0)
			fail("VIDIOC_DQBUF");
		if (buf.index >= BUFFER_COUNT) {
			errno = EPROTO;
			fail("driver returned invalid buffer index");
		}

		used = planes[0].bytesused;
		if (!used || used > mapped[buf.index].length)
			used = mapped[buf.index].length;
		bytes = mapped[buf.index].addr;
		for (j = 0; j < used; j++) {
			if (bytes[j] == 0)
				zeroes++;
			else if (bytes[j] == SENTINEL)
				sentinels++;
			else
				other++;
		}

		printf("CAPTURE_FRAME: sequence=%u index=%u bytesused=%u inspected=%zu zero=%zu sentinel=%zu other=%zu first=%02x%02x%02x%02x\n",
		       buf.sequence, buf.index, planes[0].bytesused, used,
		       zeroes, sentinels, other, bytes[0], bytes[1], bytes[2], bytes[3]);
		fflush(stdout);
		(void)fsync(STDOUT_FILENO);
		write_all(output_fd, bytes, used);
	}

	if (fsync(output_fd) < 0)
		fail("fsync output");
	close(output_fd);
	printf("CAPTURE_STREAMOFF: entering ioctl\n");
	fflush(stdout);
	(void)fsync(STDOUT_FILENO);
	if (xioctl(video_fd, VIDIOC_STREAMOFF, &type) < 0)
		fail("VIDIOC_STREAMOFF");
	printf("CAPTURE_DONE\n");
	fflush(stdout);
	(void)fsync(STDOUT_FILENO);

	for (i = 0; i < BUFFER_COUNT; i++)
		munmap(mapped[i].addr, mapped[i].length);
	close(video_fd);
	return EXIT_SUCCESS;
}
