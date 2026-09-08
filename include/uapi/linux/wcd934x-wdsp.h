/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef _UAPI_LINUX_WCD934X_WDSP_H
#define _UAPI_LINUX_WCD934X_WDSP_H

#include <linux/ioctl.h>
#include <linux/types.h>

struct wcd934x_wdsp_xfer {
	__u32 remote_addr;
	__u32 len;
	__u64 data;
};

#define WCD934X_WDSP_IOC_MAGIC		'W'
#define WCD934X_WDSP_IOC_MEM_READ	_IOWR(WCD934X_WDSP_IOC_MAGIC, 0x00, \
					      struct wcd934x_wdsp_xfer)
#define WCD934X_WDSP_IOC_MEM_WRITE	_IOW(WCD934X_WDSP_IOC_MAGIC, 0x01, \
					     struct wcd934x_wdsp_xfer)

#endif
