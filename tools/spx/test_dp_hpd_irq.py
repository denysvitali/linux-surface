#!/usr/bin/env python3
"""Exercise real firmware HPD IRQ resource ownership without display hardware."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class FirmwareHPDTest(unittest.TestCase):
    def test_aux_phy_ownership(self):
        source = (Path(__file__).resolve().parents[2] /
                  "drivers/gpu/drm/msm/dp/dp_display.c").read_text()
        match = re.search(r"^int msm_dp_bridge_hpd_irq\([^{}]*\)\n\{.*?^\}",
                          source, re.M | re.S)
        self.assertIsNotNone(match)
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define DRM_MODE_CONNECTOR_DisplayPort 10
#define drm_dbg_dp(...) ((void)0)
struct device { int unused; };
struct platform_device { struct device dev; };
struct msm_dp { struct platform_device *pdev; bool power_on; };
struct msm_dp_display_private {
    struct msm_dp msm_dp_display;
    int event_mutex, plugged_lock;
    bool plugged, phy_initialized;
};
struct msm_dp_bridge { struct msm_dp *msm_dp_display; };
struct bridge_funcs { void (*hpd_notify)(void); };
struct drm_bridge {
    int type, hpd_state_mutex, hpd_mutex;
    bool hpd_cb;
    struct bridge_funcs *funcs;
    struct msm_dp_bridge *owner;
};
static int locks, entered, pm_gets, pm_puts, acquired, released, irq_calls;
static int pm_result, irq_result;
static bool live = true;
static bool drm_bridge_enter(struct drm_bridge *b, int *idx)
{ *idx = 1; entered += live; return live; }
static void drm_bridge_exit(int idx) { assert(idx == 1); --entered; }
static void mutex_lock(int *m) { ++locks; }
static void mutex_unlock(int *m) { --locks; }
static void msm_dp_bridge_hpd_notify(void) {}
static struct msm_dp_bridge *to_dp_bridge(struct drm_bridge *b)
{ return b->owner; }
static int pm_runtime_resume_and_get(struct device *d)
{ ++pm_gets; return pm_result; }
static void pm_runtime_put_sync(struct device *d) { ++pm_puts; }
bool msm_dp_display_host_phy_init(struct msm_dp_display_private *d)
{
    if (d->phy_initialized)
        return false;
    d->phy_initialized = true;
    ++acquired;
    return true;
}
void msm_dp_display_host_phy_exit(struct msm_dp_display_private *d)
{ assert(d->phy_initialized); d->phy_initialized = false; ++released; }
static int msm_dp_irq_hpd_handle(struct msm_dp_display_private *d)
{
    /* Runtime PM alone does not initialize the external AUX PHY. */
    assert(d->phy_initialized && "AUX attempted with PHY off");
    ++irq_calls;
    return irq_result;
}
'''
        cases = r'''
static void run(bool phy, bool power, bool plugged, bool hpd,
                int pm, int irq, int expected)
{
    struct platform_device pdev = {0};
    struct msm_dp_display_private dp = {
        .msm_dp_display = { .pdev = &pdev, .power_on = power },
        .plugged = plugged, .phy_initialized = phy,
    };
    struct msm_dp_bridge owner = { .msm_dp_display = &dp.msm_dp_display };
    struct bridge_funcs funcs = { .hpd_notify = msm_dp_bridge_hpd_notify };
    struct drm_bridge bridge = {
        .type = DRM_MODE_CONNECTOR_DisplayPort, .hpd_cb = hpd,
        .funcs = &funcs, .owner = &owner,
    };
    locks = entered = pm_gets = pm_puts = acquired = released = irq_calls = 0;
    pm_result = pm;
    irq_result = irq;
    assert(msm_dp_bridge_hpd_irq(&bridge) == expected);
    bool called = hpd && plugged && pm >= 0;
    assert(irq_calls == called);
    assert(pm_gets == (hpd && plugged));
    assert(pm_puts == called);
    assert(acquired == (called && !phy));
    assert(released == acquired);
    assert(dp.phy_initialized == phy);
    assert(dp.msm_dp_display.power_on == power);
    assert(locks == 0 && entered == 0);
}
int main(void)
{
    run(false, false, true, true, 0, 0, 0);
    run(false, false, true, true, 0, -EINVAL, -EINVAL);
    run(false, false, true, true, 0, -ETIMEDOUT, -ETIMEDOUT);
    run(true, true, true, true, 0, 0, 0);
    run(true, true, true, true, 0, -EINVAL, -EINVAL);
    run(true, false, true, true, 0, 0, 0);
    run(false, false, true, true, -EIO, 0, -EIO);
    run(false, false, false, true, 0, 0, -ENOTCONN);
    run(false, false, true, false, 0, 0, -EAGAIN);
    assert(msm_dp_bridge_hpd_irq(NULL) == -ENODEV);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="spx-dp-hpd-") as temp:
            c_file = Path(temp) / "hpd.c"
            binary = Path(temp) / "hpd"
            c_file.write_text(harness + match.group() + cases)
            subprocess.run(["cc", "-std=gnu11", "-Wall", "-Werror",
                            str(c_file), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
