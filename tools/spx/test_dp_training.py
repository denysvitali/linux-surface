#!/usr/bin/env python3
"""Exercise the real DP retry/fallback control flow without display hardware."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class DPTrainingTest(unittest.TestCase):
    def test_stream_retraining_errors(self):
        source = (Path(__file__).resolve().parents[2] /
                  "drivers/gpu/drm/msm/dp/dp_ctrl.c").read_text()
        match = re.search(r"^int msm_dp_ctrl_prepare_stream_on"
                          r"\([^{}]*\)\n\{.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(match)
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define drm_dbg_dp(...) ((void)0)
#define DRM_ERROR(...) ((void)0)
#define DP_PHY_DPRX 0
struct msm_dp_ctrl { int unused; };
struct msm_dp_panel { int unused; };
struct msm_dp_ctrl_private {
    struct msm_dp_ctrl msm_dp_ctrl;
    bool link_clks_on;
};
static int retrain_result, clock_result, retrained, cleared, teardown;
static bool channel_eq;
static int msm_dp_ctrl_enable_mainlink_clocks(struct msm_dp_ctrl_private *c,
                                            struct msm_dp_panel *p)
{ return clock_result; }
static bool msm_dp_ctrl_channel_eq_ok(struct msm_dp_ctrl_private *c)
{ return channel_eq; }
static int msm_dp_ctrl_link_retrain(struct msm_dp_ctrl_private *c,
                                  struct msm_dp_panel *p)
{ ++retrained; return retrain_result; }
static void msm_dp_ctrl_clear_training_pattern(struct msm_dp_ctrl_private *c,
                                               struct msm_dp_panel *p, int phy)
{ ++cleared; }
int msm_dp_ctrl_deinitialize_mainlink(struct msm_dp_ctrl_private *c,
                                    struct msm_dp_panel *p)
{ ++teardown; return 0; }
'''
        cases = r'''
static void run(bool force, bool eq, int result)
{
    struct msm_dp_ctrl_private ctrl = { .link_clks_on = true };
    struct msm_dp_panel panel = {0};
    retrained = cleared = teardown = 0;
    channel_eq = eq;
    retrain_result = result;
    bool needed = force || !eq;
    int expected = needed ? result : 0;
    assert(msm_dp_ctrl_prepare_stream_on(&ctrl.msm_dp_ctrl, &panel, force)
           == expected);
    assert(retrained == needed);
    assert(cleared == 1);
    assert(teardown == (expected != 0));
}
int main(void)
{
    run(true, true, -ETIMEDOUT);
    run(false, false, -EIO);
    run(true, true, 0);
    run(false, false, 0);
    run(false, true, -ETIMEDOUT);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="spx-dp-retrain-") as temp:
            c_file = Path(temp) / "retrain.c"
            binary = Path(temp) / "retrain"
            c_file.write_text(harness + match.group() + cases)
            subprocess.run(["cc", "-std=gnu11", "-Wall", "-Werror",
                            str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_retry_results(self):
        source = (Path(__file__).resolve().parents[2] /
                  "drivers/gpu/drm/msm/dp/dp_ctrl.c").read_text()
        names = ("msm_dp_ctrl_link_rate_down_shift",
                 "msm_dp_ctrl_link_lane_down_shift", "msm_dp_ctrl_on_link")
        functions = []
        for name in names:
            match = re.search(r"^(?:static )?int " + name +
                              r"\([^{}]*\)\n\{.*?^\}", source, re.M | re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define drm_dbg_dp(...) ((void)0)
#define DRM_ERROR(...) ((void)0)
#define DP_LINK_STATUS_SIZE 6
#define DP_TRAINING_NONE 0
#define DP_TRAINING_1 1
#define DP_TRAINING_2 2
#define DP_PHY_DPRX 0
#define DP_TEST_LINK_PHY_TEST_PATTERN 1
struct msm_dp_ctrl { int unused; };
struct msm_dp_link_info {
    unsigned int rate, num_lanes, rate_set, supported_rates[8];
};
struct link {
    struct msm_dp_link_info link_params;
    unsigned int sink_request;
    struct { int p_level, v_level; } phy_params;
};
struct msm_dp_panel {
    struct msm_dp_link_info link_info;
    struct { struct { unsigned int clock; } drm_mode;
             bool out_fmt_is_yuv_420; } msm_dp_mode;
};
struct msm_dp_ctrl_private {
    struct msm_dp_ctrl msm_dp_ctrl;
    struct link *link;
    void *aux, *drm_dev;
};
static int attempts, resets, teardown, cleared;
static int success_at, stage, aux_error, reset_error, clock_error;
static bool connected;
static int msm_dp_ctrl_core_clk_enable(struct msm_dp_ctrl *c) { return 0; }
static int msm_dp_ctrl_enable_mainlink_clocks(struct msm_dp_ctrl_private *c,
                                            struct msm_dp_panel *p)
{ return clock_error; }
static int msm_dp_ctrl_setup_main_link(struct msm_dp_ctrl_private *c,
                                       struct msm_dp_panel *p, unsigned int *s)
{
    ++attempts;
    *s = stage;
    if (c->link->sink_request & DP_TEST_LINK_PHY_TEST_PATTERN)
        return 0;
    return attempts == success_at ? 0 : -ETIMEDOUT;
}
static bool msm_dp_aux_is_link_connected(void *a) { return connected; }
static int drm_dp_dpcd_read_link_status(void *a, u8 *s)
{ return aux_error ? aux_error : DP_LINK_STATUS_SIZE; }
static bool msm_dp_ctrl_clock_recovery_any_ok(u8 *s, unsigned int lanes)
{ return true; }
static bool drm_dp_clock_recovery_ok(u8 *s, unsigned int lanes)
{ return false; }
static void msm_dp_ctrl_clear_training_pattern(struct msm_dp_ctrl_private *c,
                                               struct msm_dp_panel *p, int phy)
{ ++cleared; }
static int msm_dp_ctrl_reinitialize_mainlink(struct msm_dp_ctrl_private *c,
                                            struct msm_dp_panel *p)
{ ++resets; return reset_error; }
static int msm_dp_ctrl_deinitialize_mainlink(struct msm_dp_ctrl_private *c,
                                            struct msm_dp_panel *p)
{ ++teardown; return 0; }
'''
        cases = r'''
static void run(int success, int training_stage, int aux, bool attached,
                int reset, int clocks, int expected, int tries, int reinit,
                int deinit)
{
    struct link link = {0};
    struct msm_dp_ctrl_private ctrl = { .link = &link };
    struct msm_dp_panel panel = {
        .link_info = { .rate = 540000, .num_lanes = 4 },
        .msm_dp_mode.drm_mode.clock = 148500,
    };
    attempts = resets = teardown = cleared = 0;
    success_at = success;
    stage = training_stage;
    aux_error = aux;
    connected = attached;
    reset_error = reset;
    clock_error = clocks;
    int result = msm_dp_ctrl_on_link(&ctrl.msm_dp_ctrl, &panel);
    if (result != expected)
        fprintf(stderr, "expected=%d actual=%d attempts=%d resets=%d teardown=%d\n",
                expected, result, attempts, resets, teardown);
    assert(result == expected);
    assert(attempts == tries);
    assert(resets == reinit);
    assert(teardown == deinit);
    assert(cleared == deinit + (training_stage == DP_TRAINING_2 ? reinit : 0));
}
int main(void)
{
    run(1, DP_TRAINING_1, 0, true, 0, 0, 0, 1, 0, 0);
    run(4, DP_TRAINING_1, 0, true, 0, 0, 0, 4, 3, 0);
    /* Four failed attempts, successful fallback/reset, no trained link. */
    run(0, DP_TRAINING_1, 0, true, 0, 0, -ECONNRESET, 4, 4, 1);
    run(0, DP_TRAINING_2, 0, true, 0, 0, -ECONNRESET, 3, 2, 1);
    run(0, DP_TRAINING_1, -ETIMEDOUT, true, 0, 0, -ECONNRESET, 1, 0, 1);
    run(0, DP_TRAINING_2, -ETIMEDOUT, true, 0, 0, -ECONNRESET, 1, 0, 1);
    run(0, DP_TRAINING_1, 0, false, 0, 0, -ECONNRESET, 1, 0, 1);
    run(0, DP_TRAINING_1, 0, true, -EIO, 0, -ECONNRESET, 1, 1, 1);
    run(0, DP_TRAINING_1, 0, true, 0, -EIO, -EIO, 0, 0, 0);
    struct link link = { .sink_request = DP_TEST_LINK_PHY_TEST_PATTERN };
    struct msm_dp_ctrl_private ctrl = { .link = &link };
    struct msm_dp_panel panel = {0};
    attempts = resets = teardown = cleared = clock_error = 0;
    success_at = 0;
    assert(msm_dp_ctrl_on_link(&ctrl.msm_dp_ctrl, &panel) == 0);
    assert(attempts == 1 && resets == 0 && teardown == 0 && cleared == 0);
    assert(msm_dp_ctrl_on_link(NULL, &panel) == -EINVAL);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="spx-dp-training-") as temp:
            c_file = Path(temp) / "training.c"
            binary = Path(temp) / "training"
            c_file.write_text(harness + "\n".join(functions) + cases)
            subprocess.run(["cc", "-std=gnu11", "-Wall", "-Werror",
                            str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
