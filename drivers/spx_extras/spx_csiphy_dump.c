// SPDX-License-Identifier: GPL-2.0
/*
 * spx_csiphy_dump - find the real CSIPHY CMN block inside the camss window.
 *
 * Why this exists
 * ---------------
 * Measured 2026-08-07 with the pipeline OPEN (so the block is demonstrably
 * powered and clocked - titan_top_gdsc "on", cam_cc_csiphy2_clk enabled at
 * 400MHz):
 *
 *     VFE:0  HW Version = 1.2.1        <- real
 *     CSID:0 HW Version = 1.0.0        <- real
 *     CSIPHY 3PH HW Version = 0x00000000   <- dead
 *
 * So the register path works; only the CSIPHY window reads back zero. Either
 * 0xac5a000 is not the CSIPHY on sc8180x, or the driver's CMN sub-block offset
 * (regs->offset = 0x800 for CAMSS_8280XP) is wrong for this revision - the
 * driver reads its version from COMMON_STATUS 12..14 at that offset.
 *
 * This dumps the window and reports every non-zero word, which shows whether
 * ANY register responds and where the CMN block really starts.
 *
 * ONLY load this while the pipeline is open, otherwise the block is unpowered.
 * Reads are safe (they return 0 rather than hanging - that is the whole
 * observation); this module never writes.
 *
 * Loads with -EAGAIN by design so it can be re-run without rmmod.
 */
#include <linux/module.h>
#include <linux/io.h>

static unsigned long base = 0xac5a000;
module_param(base, ulong, 0644);
MODULE_PARM_DESC(base, "physical base to dump (default csiphy2 window)");

static unsigned int len = 0x2000;
module_param(len, uint, 0644);
MODULE_PARM_DESC(len, "bytes to dump");

static int __init spx_csiphy_dump_init(void)
{
	void __iomem *p;
	unsigned int off, nonzero = 0;

	p = ioremap(base, len);
	if (!p) {
		pr_info("spxphy: ioremap 0x%lx failed\n", base);
		return -EAGAIN;
	}

	pr_info("spxphy: dumping 0x%lx..0x%lx\n", base, base + len);
	for (off = 0; off < len; off += 4) {
		u32 v = readl_relaxed(p + off);

		if (v) {
			if (nonzero < 64)
				pr_info("spxphy:   +0x%04x = 0x%08x\n", off, v);
			nonzero++;
		}
	}
	pr_info("spxphy: %u non-zero words in 0x%x bytes%s\n",
		nonzero, len,
		nonzero ? "" : "  <-- WHOLE WINDOW DEAD (wrong address or unpowered)");
	iounmap(p);
	return -EAGAIN;
}

static void __exit spx_csiphy_dump_exit(void) { }
module_init(spx_csiphy_dump_init);
module_exit(spx_csiphy_dump_exit);
MODULE_DESCRIPTION("SPX CSIPHY register-window prober");
MODULE_LICENSE("GPL");
