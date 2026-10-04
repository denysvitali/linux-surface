// SPDX-License-Identifier: GPL-2.0-only
/* Read-only RTC/NTP sample. No ADJ modes, RTC_SET_TIME or clock writes. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/rtc.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static double seconds(struct timespec t)
{
	return t.tv_sec + t.tv_nsec / 1e9;
}

int main(void)
{
	struct rtc_time rtc = {0};
	struct timespec before, after, monotonic;
	int fd;

	fd = open("/dev/rtc0", O_RDONLY | O_CLOEXEC);
	if (fd < 0) { perror("open RTC"); return 1; }
	if (clock_gettime(CLOCK_BOOTTIME, &monotonic) ||
	    clock_gettime(CLOCK_REALTIME, &before) ||
	    ioctl(fd, RTC_RD_TIME, &rtc) ||
	    clock_gettime(CLOCK_REALTIME, &after)) {
		perror("read clocks"); close(fd); return 1;
	}
	close(fd);
	struct tm tm = { .tm_sec = rtc.tm_sec, .tm_min = rtc.tm_min,
		.tm_hour = rtc.tm_hour, .tm_mday = rtc.tm_mday,
		.tm_mon = rtc.tm_mon, .tm_year = rtc.tm_year };
	time_t epoch = timegm(&tm);
	if (epoch < 0) { perror("RTC epoch"); return 1; }
	printf("{\"monotonic\":%.9f,\"realtime_before\":%.9f,"
	       "\"realtime_after\":%.9f,\"rtc_epoch\":%lld}\n",
	       seconds(monotonic), seconds(before), seconds(after),
	       (long long)epoch);
	return 0;
}
