/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _Q6_PCM_ROUTING_H
#define _Q6_PCM_ROUTING_H

#include <linux/types.h>

int q6routing_stream_open(int fedai_id, int perf_mode,
			   int stream_id, int stream_type);
void q6routing_stream_close(int fedai_id, int stream_type);

int q6routing_stream_open_asm(int fedai_id, int perf_mode, int stream_id,
			    int stream_type, bool asm_reused);
void q6routing_stream_close_asm(int fedai_id, int stream_type, bool asm_parked);

#endif /*_Q6_PCM_ROUTING_H */
