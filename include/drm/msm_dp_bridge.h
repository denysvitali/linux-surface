/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __DRM_MSM_DP_BRIDGE_H__
#define __DRM_MSM_DP_BRIDGE_H__

struct drm_bridge;

int msm_dp_bridge_hpd_irq(struct drm_bridge *bridge);

#endif /* __DRM_MSM_DP_BRIDGE_H__ */
