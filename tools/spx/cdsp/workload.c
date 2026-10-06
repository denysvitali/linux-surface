// SPDX-License-Identifier: BSD-3-Clause
/* Freestanding FastRPC dispatcher, not installed or invoked on the device.
 * ABI: Qualcomm fastrpc inc/remote.h and src/apps_std_skel.c.
 * Method0: two LE32 words -> wrapping LE32 sum (one input, one output).
 * Method1: two 64-element signed LE32 vectors -> wrapping LE64 dot product.
 * No allocation, system calls, loader callbacks or external runtime symbols.
 */
typedef __UINT32_TYPE__ u32;
typedef __INT32_TYPE__ s32;
typedef __UINT64_TYPE__ u64;
typedef __INT64_TYPE__ s64;
typedef __SIZE_TYPE__ size_type;

typedef union {
	struct { void *pv; size_type len; } buf;
	u32 handle;
	u64 handle64;
	struct { s32 fd; u32 offset; } dma;
} remote_arg;

#if __SIZEOF_POINTER__ == 4
_Static_assert(sizeof(remote_arg) == 8, "FastRPC DSP remote_arg ABI");
#endif

static u32 read32(const unsigned char *p)
{
	return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}

static void write32(unsigned char *p, u32 value)
{
	p[0] = value;
	p[1] = value >> 8;
	p[2] = value >> 16;
	p[3] = value >> 24;
}

__attribute__((visibility("default")))
int spx_workload_skel_invoke(u32 scalar, remote_arg *args)
{
	if (!args)
		return 1;
	if (scalar == 0x00010100) {
		if (!args[0].buf.pv || !args[1].buf.pv ||
		    args[0].buf.len != 8 || args[1].buf.len != 4)
			return 1;
		const unsigned char *input = args[0].buf.pv;
		write32(args[1].buf.pv, read32(input) + read32(input + 4));
		return 0;
	}
	if (scalar == 0x01020100) {
		if (!args[0].buf.pv || !args[1].buf.pv || !args[2].buf.pv ||
		    args[0].buf.len != 256 || args[1].buf.len != 256 ||
		    args[2].buf.len != 8)
			return 1;
		const unsigned char *a = args[0].buf.pv, *b = args[1].buf.pv;
		u64 sum = 0;
		for (unsigned int i = 0; i < 64; i++)
			sum += (u64)((s64)(s32)read32(a + 4 * i) *
				     (s64)(s32)read32(b + 4 * i));
		write32(args[2].buf.pv, (u32)sum);
		write32((unsigned char *)args[2].buf.pv + 4, (u32)(sum >> 32));
		return 0;
	}
	return 1;
}
