/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Copyright (c) 2012-2016, The Linux Foundation. All rights reserved.
 * Copyright (C) 2017 Linaro Ltd.
 */
#ifndef __VENUS_HFI_VENUS_H__
#define __VENUS_HFI_VENUS_H__

#include <linux/types.h>

struct venus_core;
struct venus_inst;

void venus_hfi_session_poll(struct venus_core *core);
void venus_hfi_session_timeout(struct venus_inst *inst, u32 command);
void venus_hfi_queue_setup_timeout(struct venus_inst *inst, const char *phase,
				   int ret);
void venus_hfi_startup_dump(struct venus_core *core);
void venus_hfi_destroy(struct venus_core *core);
int venus_hfi_create(struct venus_core *core);
void venus_hfi_queues_reinit(struct venus_core *core);

#endif
