// SPDX-License-Identifier: GPL-2.0
/*
 * WCD9340 CPE/WDSP firmware loader over the codec's AUDD SPI interface.
 *
 * The WCD9340 contains an Xtensa DSP (called CPE or WDSP by Qualcomm).
 * Surface Pro X Windows boots it through QUP0 serial engine 3 before opening
 * the speaker graph.  The upstream WCD934x driver does not implement this
 * path.  This driver intentionally covers only the deterministic hardware
 * bring-up and firmware download; the GLINK/GCS graph transport is separate.
 */

#include <linux/clk.h>
#include <linux/completion.h>
#include <linux/device.h>
#include <linux/elf.h>
#include <linux/firmware.h>
#include <linux/interrupt.h>
#include <linux/miscdevice.h>
#include <linux/mfd/wcd934x/registers.h>
#include <linux/mfd/wcd934x/wcd934x.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/overflow.h>
#include <linux/regmap.h>
#include <linux/slimbus.h>
#include <linux/spi/spi.h>
#include <linux/uaccess.h>
#include <uapi/linux/wcd934x-wdsp.h>

#define WCD_SPI_CMD_NOP		0x00
#define WCD_SPI_CMD_WREN	0x06
#define WCD_SPI_CMD_CLKREQ	0xda
#define WCD_SPI_CMD_RDSR	0x05
#define WCD_SPI_CMD_IRR		0x81
#define WCD_SPI_CMD_IRW		0x82
#define WCD_SPI_CMD_MIOR	0x83
#define WCD_SPI_CMD_FREAD	0x0b
#define WCD_SPI_CMD_MIOW	0x02

#define WCD_SPI_READ_SINGLE_LEN	0x13
#define WCD_SPI_FREAD_HEADER_LEN	0x13
#define WCD_SPI_MULTI_ALIGN	16
#define WCD_SPI_MULTI_MAX	((64 * 1024) - 32)
#define WCD_SPI_ADDR_MASK	GENMASK(23, 0)
#define WCD_SPI_IPC_CTL_HOST	0x012014

#define WCD_SPI_SLAVE_CONFIG	0x0c
#define WCD_SPI_SLAVE_TRNS_LEN	0x50

#define WCD_WDSP_BOOT_TIMEOUT_MS	3000
#define WCD_WDSP_USER_XFER_MAX		(64 * 1024)

static const u8 wcd_mem_enable_values[] = {
	0xfe, 0xfc, 0xf8, 0xf0, 0xe0, 0xc0, 0x80, 0x00,
};

struct wcd934x_wdsp {
	struct spi_device *spi;
	struct wcd934x_ddata *codec;
	struct device *codec_dev;
	struct completion boot_done;
	struct miscdevice miscdev;
	struct mutex xfer_lock;
	const char *firmware_name;
	u32 mem_base;
	int ipc_irq;
	int err_irq;
	int boot_result;
	bool clock_on;
	bool booted;
};

static int wcd_wdsp_spi_sync(struct wcd934x_wdsp *wdsp,
			     const void *tx, void *rx, size_t len)
{
	struct spi_transfer xfer = {
		.tx_buf = tx,
		.rx_buf = rx,
		.len = len,
	};

	return spi_sync_transfer(wdsp->spi, &xfer, 1);
}

static int wcd_wdsp_spi_write_then_read(struct wcd934x_wdsp *wdsp,
					const void *tx, size_t tx_len,
					void *rx, size_t rx_len)
{
	struct spi_transfer xfers[2] = {
		{
			.tx_buf = tx,
			.len = tx_len,
		}, {
			.rx_buf = rx,
			.len = rx_len,
		},
	};

	return spi_sync_transfer(wdsp->spi, xfers, ARRAY_SIZE(xfers));
}

static int wcd_wdsp_internal_read(struct wcd934x_wdsp *wdsp, u8 reg, u32 *val)
{
	u8 cmd[4] = { WCD_SPI_CMD_IRR, reg, 0, 0 };
	__be32 raw;
	int ret;

	ret = wcd_wdsp_spi_write_then_read(wdsp, cmd, sizeof(cmd),
					   &raw, sizeof(raw));
	if (!ret)
		*val = be32_to_cpu(raw);

	return ret;
}

static int wcd_wdsp_internal_write(struct wcd934x_wdsp *wdsp, u8 reg, u32 val)
{
	u8 cmd[6] = { WCD_SPI_CMD_IRW, reg };
	__be32 raw = cpu_to_be32(val);

	memcpy(cmd + 2, &raw, sizeof(raw));
	return spi_write(wdsp->spi, cmd, sizeof(cmd));
}

static int wcd_wdsp_clock_enable(struct wcd934x_wdsp *wdsp)
{
	u8 clkreq[4] = { WCD_SPI_CMD_CLKREQ, 0xba, 0x80, 0x00 };
	u8 cmd;
	__be32 raw_status;
	u32 status;
	int ret;

	if (wdsp->clock_on)
		return 0;

	cmd = WCD_SPI_CMD_NOP;
	ret = spi_write(wdsp->spi, &cmd, sizeof(cmd));
	if (ret)
		return ret;

	ret = spi_write(wdsp->spi, clkreq, sizeof(clkreq));
	if (ret)
		return ret;
	usleep_range(500, 550);

	cmd = WCD_SPI_CMD_NOP;
	ret = spi_write(wdsp->spi, &cmd, sizeof(cmd));
	if (ret)
		return ret;

	cmd = WCD_SPI_CMD_RDSR;
	ret = wcd_wdsp_spi_write_then_read(wdsp, &cmd, sizeof(cmd),
					   &raw_status, sizeof(raw_status));
	if (ret)
		return ret;

	status = be32_to_cpu(raw_status);
	if (!status) {
		dev_err(&wdsp->spi->dev, "AUDD SPI clock request returned status 0\n");
		return -EIO;
	}

	wdsp->clock_on = true;
	return 0;
}

static int wcd_wdsp_clock_disable(struct wcd934x_wdsp *wdsp);

static int wcd_wdsp_write_single(struct wcd934x_wdsp *wdsp, u32 addr,
				 const u8 *data)
{
	u8 frame[8] = {};
	__be32 cmd = cpu_to_be32((WCD_SPI_CMD_MIOW << 24) |
				 (addr & WCD_SPI_ADDR_MASK));

	memcpy(frame, &cmd, sizeof(cmd));
	memcpy(frame + sizeof(cmd), data, sizeof(u32));
	return spi_write(wdsp->spi, frame, sizeof(frame));
}

static int wcd_wdsp_read_single(struct wcd934x_wdsp *wdsp, u32 addr, u8 *data)
{
	u8 cmd[WCD_SPI_READ_SINGLE_LEN] = {};
	__be32 frame = cpu_to_be32((WCD_SPI_CMD_MIOR << 24) |
				   (addr & WCD_SPI_ADDR_MASK));

	memcpy(cmd, &frame, sizeof(frame));
	return wcd_wdsp_spi_write_then_read(wdsp, cmd, sizeof(cmd),
					   data, sizeof(u32));
}

static int wcd_wdsp_write_multi(struct wcd934x_wdsp *wdsp, u32 addr,
				const u8 *data, size_t len)
{
	__be32 frame = cpu_to_be32((WCD_SPI_CMD_MIOW << 24) |
				   (addr & WCD_SPI_ADDR_MASK));
	u8 *buf;
	int ret;

	buf = kmalloc(len + sizeof(frame), GFP_KERNEL | GFP_DMA);
	if (!buf)
		return -ENOMEM;

	memcpy(buf, &frame, sizeof(frame));
	memcpy(buf + sizeof(frame), data, len);
	ret = spi_write(wdsp->spi, buf, len + sizeof(frame));
	kfree(buf);

	return ret;
}

static int wcd_wdsp_read_multi(struct wcd934x_wdsp *wdsp, u32 addr,
			       u8 *data, size_t len)
{
	__be32 frame = cpu_to_be32((WCD_SPI_CMD_FREAD << 24) |
				   (addr & WCD_SPI_ADDR_MASK));
	size_t xfer_len = WCD_SPI_FREAD_HEADER_LEN + len;
	u8 *tx;
	u8 *rx;
	int ret;

	tx = kzalloc(xfer_len, GFP_KERNEL | GFP_DMA);
	rx = kzalloc(xfer_len, GFP_KERNEL | GFP_DMA);
	if (!tx || !rx) {
		ret = -ENOMEM;
		goto out;
	}

	memcpy(tx, &frame, sizeof(frame));
	ret = wcd_wdsp_spi_sync(wdsp, tx, rx, xfer_len);
	if (!ret)
		memcpy(data, rx + WCD_SPI_FREAD_HEADER_LEN, len);
out:
	kfree(rx);
	kfree(tx);
	return ret;
}

static int __wcd_wdsp_mem_xfer(struct wcd934x_wdsp *wdsp, u32 addr,
			       u8 *data, size_t len, bool write)
{
	size_t xfer;
	int ret;

	if (!IS_ALIGNED(addr, sizeof(u32)) || !IS_ALIGNED(len, sizeof(u32)))
		return -EINVAL;

	while (len && !IS_ALIGNED(addr, WCD_SPI_MULTI_ALIGN)) {
		ret = write ? wcd_wdsp_write_single(wdsp, addr, data) :
			      wcd_wdsp_read_single(wdsp, addr, data);
		if (ret)
			return ret;
		addr += sizeof(u32);
		data += sizeof(u32);
		len -= sizeof(u32);
	}

	while (len >= WCD_SPI_MULTI_ALIGN) {
		xfer = min_t(size_t, round_down(len, WCD_SPI_MULTI_ALIGN),
			     WCD_SPI_MULTI_MAX);
		ret = write ? wcd_wdsp_write_multi(wdsp, addr, data, xfer) :
			      wcd_wdsp_read_multi(wdsp, addr, data, xfer);
		if (ret)
			return ret;
		addr += xfer;
		data += xfer;
		len -= xfer;
	}

	while (len) {
		ret = write ? wcd_wdsp_write_single(wdsp, addr, data) :
			      wcd_wdsp_read_single(wdsp, addr, data);
		if (ret)
			return ret;
		addr += sizeof(u32);
		data += sizeof(u32);
		len -= sizeof(u32);
	}

	return 0;
}

static int wcd_wdsp_mem_write(struct wcd934x_wdsp *wdsp, u32 addr,
			      const void *data, size_t len)
{
	int ret;

	mutex_lock(&wdsp->xfer_lock);
	ret = __wcd_wdsp_mem_xfer(wdsp, addr, (u8 *)data, len, true);
	mutex_unlock(&wdsp->xfer_lock);
	return ret;
}

static int wcd_wdsp_mem_read(struct wcd934x_wdsp *wdsp, u32 addr,
			     void *data, size_t len)
{
	int ret;

	mutex_lock(&wdsp->xfer_lock);
	ret = __wcd_wdsp_mem_xfer(wdsp, addr, data, len, false);
	mutex_unlock(&wdsp->xfer_lock);
	return ret;
}

static int wcd_wdsp_clock_disable(struct wcd934x_wdsp *wdsp)
{
	u32 one = 1;
	int ret;

	if (!wdsp->clock_on)
		return 0;

	ret = wcd_wdsp_write_single(wdsp, WCD_SPI_IPC_CTL_HOST, (u8 *)&one);
	if (!ret)
		wdsp->clock_on = false;
	return ret;
}

static int wcd_wdsp_spi_init(struct wcd934x_wdsp *wdsp)
{
	u8 cmd = WCD_SPI_CMD_WREN;
	u32 val;
	int ret;

	ret = wcd_wdsp_clock_enable(wdsp);
	if (ret)
		return ret;

	ret = spi_write(wdsp->spi, &cmd, sizeof(cmd));
	if (ret)
		return ret;

	ret = wcd_wdsp_internal_write(wdsp, WCD_SPI_SLAVE_CONFIG, 0x0f3d0800);
	if (ret)
		return ret;

	ret = wcd_wdsp_internal_read(wdsp, WCD_SPI_SLAVE_TRNS_LEN, &val);
	if (ret)
		return ret;

	return wcd_wdsp_internal_write(wdsp, WCD_SPI_SLAVE_TRNS_LEN,
				       val | GENMASK(31, 16));
}

static int wcd_wdsp_codec_clocks_enable(struct wcd934x_wdsp *wdsp)
{
	struct regmap *map = wdsp->codec->regmap;
	unsigned int lock;
	int retry;
	int ret;

	ret = clk_prepare_enable(wdsp->codec->extclk);
	if (ret)
		return ret;

	regmap_update_bits(map, WCD934X_CPE_SS_CPE_CTL, 0x05, 0x00);
	regmap_update_bits(map, WCD934X_CLK_SYS_MCLK2_PRG1, 0x80, 0x80);
	regmap_update_bits(map, WCD934X_CPE_FLL_USER_CTL_5, 0xf3, 0x13);
	regmap_write(map, WCD934X_CPE_FLL_L_VAL_CTL_0, 0x50);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CTL, 0x02, 0x02);
	regmap_write(map, WCD934X_CPE_FLL_USER_CTL_6, 0x6d);
	regmap_write(map, WCD934X_CPE_FLL_USER_CTL_7, 0x00);
	regmap_update_bits(map, WCD934X_CPE_FLL_FLL_MODE, 0x60, 0x00);
	regmap_update_bits(map, WCD934X_CPE_FLL_FLL_MODE, 0x80, 0x80);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CFG, 0x04, 0x04);

	for (retry = 0; retry <= 5; retry++) {
		usleep_range(1000, 1100);
		ret = regmap_read(map, WCD934X_CPE_FLL_STATUS_3, &lock);
		if (ret)
			goto err;
		if (lock & BIT(0))
			break;
	}
	if (!(lock & BIT(0))) {
		dev_err(&wdsp->spi->dev, "CPE FLL failed to lock (0x%02x)\n", lock);
		ret = -EIO;
		goto err;
	}

	regmap_update_bits(map, WCD934X_CPE_FLL_FLL_MODE, 0x60, 0x20);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CFG, 0x04, 0x00);
	regmap_write(map, WCD934X_TEST_DEBUG_LVAL_NOM_LOW, 0x90);
	regmap_write(map, WCD934X_TEST_DEBUG_LVAL_NOM_HIGH, 0x00);
	regmap_write(map, WCD934X_TEST_DEBUG_LVAL_SVS_SVS2_LOW, 0x50);
	regmap_write(map, WCD934X_TEST_DEBUG_LVAL_SVS_SVS2_HIGH, 0x00);
	regmap_update_bits(map, WCD934X_CPE_SS_PWR_CPEFLL_CTL, 0x03, 0x03);
	regmap_update_bits(map, WCD934X_CPE_SS_CPE_CTL, 0x05, 0x05);
	regmap_update_bits(map, WCD934X_CODEC_RPM_CLK_GATE, 0x10, 0x00);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CTL, 0x03, 0x03);

	return 0;
err:
	clk_disable_unprepare(wdsp->codec->extclk);
	return ret;
}

static void wcd_wdsp_codec_clocks_disable(struct wcd934x_wdsp *wdsp)
{
	struct regmap *map = wdsp->codec->regmap;

	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CTL, 0x03, 0x00);
	regmap_update_bits(map, WCD934X_CODEC_RPM_CLK_GATE, 0x10, 0x10);
	regmap_update_bits(map, WCD934X_CPE_SS_CPE_CTL, 0x05, 0x00);
	regmap_write(map, WCD934X_CPE_FLL_FLL_MODE, 0x20);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CFG, 0x04, 0x00);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CTL, 0x02, 0x00);
	regmap_update_bits(map, WCD934X_CPE_SS_CPAR_CTL, 0x04, 0x04);
	clk_disable_unprepare(wdsp->codec->extclk);
}

static int wcd_wdsp_memory_enable(struct wcd934x_wdsp *wdsp, bool switchable)
{
	struct regmap *map = wdsp->codec->regmap;
	unsigned int status;
	int i;
	int retry;
	int ret;

	if (!switchable) {
		for (i = 0; i < ARRAY_SIZE(wcd_mem_enable_values); i++) {
			ret = regmap_write(map,
				WCD934X_CPE_SS_PWR_CPE_SYSMEM_SHUTDOWN_0,
				wcd_mem_enable_values[i]);
			if (ret)
				return ret;
		}
		for (i = 0; i < ARRAY_SIZE(wcd_mem_enable_values); i++) {
			ret = regmap_write(map,
				WCD934X_CPE_SS_PWR_CPE_SYSMEM_SHUTDOWN_1,
				wcd_mem_enable_values[i]);
			if (ret)
				return ret;
		}
	} else {
		regmap_update_bits(map, WCD934X_CPE_SS_SOC_SW_COLLAPSE_CTL,
				   0x04, 0x00);
		regmap_update_bits(map, WCD934X_TEST_DEBUG_MEM_CTRL, 0x80, 0x80);
		regmap_update_bits(map, WCD934X_CPE_SS_SOC_SW_COLLAPSE_CTL,
				   0x01, 0x01);
		for (retry = 0; retry < 20; retry++) {
			usleep_range(100, 150);
			ret = regmap_read(map,
					WCD934X_CPE_SS_SOC_SW_COLLAPSE_CTL,
					&status);
			if (ret)
				return ret;
			if ((status & 0x02) == 0x02)
				break;
		}
		if ((status & 0x02) != 0x02)
			return -EIO;

		for (i = 0; i < ARRAY_SIZE(wcd_mem_enable_values); i++) {
			ret = regmap_write(map,
				WCD934X_CPE_SS_PWR_CPE_SYSMEM_SHUTDOWN_2,
				wcd_mem_enable_values[i]);
			if (ret)
				return ret;
		}
		for (i = 0; i < ARRAY_SIZE(wcd_mem_enable_values); i++) {
			ret = regmap_write(map,
				WCD934X_CPE_SS_PWR_CPE_SYSMEM_SHUTDOWN_3,
				wcd_mem_enable_values[i]);
			if (ret)
				return ret;
		}
		regmap_write(map, WCD934X_CPE_SS_PWR_CPE_DRAM1_SHUTDOWN, 0x05);
	}

	regmap_write(map, WCD934X_CPE_SS_PWR_CPE_SYSMEM_DEEPSLP_0, 0xff);
	regmap_write(map, WCD934X_CPE_SS_PWR_CPE_SYSMEM_DEEPSLP_1, 0x0f);
	return 0;
}

static bool wcd_wdsp_valid_elf(const struct firmware *fw,
			       const struct elf32_hdr **ehdr_out)
{
	const struct elf32_hdr *ehdr;
	size_t phdr_end;

	if (fw->size < sizeof(*ehdr))
		return false;

	ehdr = (const struct elf32_hdr *)fw->data;
	if (memcmp(ehdr->e_ident, ELFMAG, SELFMAG) ||
	    ehdr->e_ident[EI_CLASS] != ELFCLASS32 ||
	    ehdr->e_ident[EI_DATA] != ELFDATA2LSB ||
	    ehdr->e_phentsize != sizeof(struct elf32_phdr) ||
	    !ehdr->e_phnum)
		return false;

	if (check_mul_overflow((size_t)ehdr->e_phnum,
			       sizeof(struct elf32_phdr), &phdr_end) ||
	    check_add_overflow(phdr_end, (size_t)ehdr->e_phoff, &phdr_end) ||
	    phdr_end > fw->size)
		return false;

	*ehdr_out = ehdr;
	return true;
}

static int wcd_wdsp_load_class(struct wcd934x_wdsp *wdsp,
			       const struct firmware *fw,
			       const struct elf32_hdr *ehdr, bool writable)
{
	const struct elf32_phdr *phdrs;
	const struct elf32_phdr *phdr;
	u32 remote_addr;
	int i;
	int ret;

	phdrs = (const struct elf32_phdr *)(fw->data + ehdr->e_phoff);
	for (i = 0; i < ehdr->e_phnum; i++) {
		phdr = &phdrs[i];
		if (phdr->p_type != PT_LOAD || !phdr->p_filesz ||
		    !phdr->p_memsz)
			continue;
		if (!!(phdr->p_flags & PF_W) != writable)
			continue;
		if (!(phdr->p_flags & (PF_R | PF_X)) && !writable)
			continue;
		if (phdr->p_offset > fw->size ||
		    phdr->p_filesz > fw->size - phdr->p_offset ||
		    phdr->p_paddr < ehdr->e_entry ||
		    !IS_ALIGNED(phdr->p_paddr, sizeof(u32)) ||
		    !IS_ALIGNED(phdr->p_filesz, sizeof(u32)))
			return -EINVAL;

		remote_addr = phdr->p_paddr - ehdr->e_entry + wdsp->mem_base;
		if (remote_addr > WCD_SPI_ADDR_MASK ||
		    phdr->p_filesz > WCD_SPI_ADDR_MASK - remote_addr + 1)
			return -ERANGE;

		dev_info(&wdsp->spi->dev,
			 "loading %s segment %d: paddr=%#x spi=%#x size=%#x\n",
			 writable ? "RW" : "RO", i, phdr->p_paddr,
			 remote_addr, phdr->p_filesz);
		ret = wcd_wdsp_mem_write(wdsp, remote_addr,
					 fw->data + phdr->p_offset,
					 phdr->p_filesz);
		if (ret)
			return ret;
	}

	return 0;
}

static irqreturn_t wcd_wdsp_ipc_irq(int irq, void *data)
{
	struct wcd934x_wdsp *wdsp = data;

	complete(&wdsp->boot_done);
	return IRQ_HANDLED;
}

static irqreturn_t wcd_wdsp_error_irq(int irq, void *data)
{
	struct wcd934x_wdsp *wdsp = data;
	unsigned int lo = 0;
	unsigned int hi = 0;

	regmap_read(wdsp->codec->regmap,
		    WCD934X_CPE_SS_SS_ERROR_INT_STATUS_0A, &lo);
	regmap_read(wdsp->codec->regmap,
		    WCD934X_CPE_SS_SS_ERROR_INT_STATUS_0B, &hi);
	dev_err(&wdsp->spi->dev, "WDSP fatal interrupt status %#04x\n",
		lo | (hi << 8));
	return IRQ_HANDLED;
}

static int wcd_wdsp_boot(struct wcd934x_wdsp *wdsp)
{
	const struct elf32_hdr *ehdr;
	const struct firmware *fw;
	struct regmap *map = wdsp->codec->regmap;
	unsigned long timeout;
	int ret;

	ret = request_firmware(&fw, wdsp->firmware_name, &wdsp->spi->dev);
	if (ret) {
		dev_err(&wdsp->spi->dev, "cannot load %s: %d\n",
			wdsp->firmware_name, ret);
		return ret;
	}
	if (!wcd_wdsp_valid_elf(fw, &ehdr)) {
		ret = -EINVAL;
		goto out_fw;
	}

	ret = wcd_wdsp_spi_init(wdsp);
	if (ret)
		goto out_fw;

	ret = wcd_wdsp_codec_clocks_enable(wdsp);
	if (ret)
		goto out_fw;
	ret = wcd_wdsp_memory_enable(wdsp, false);
	if (ret)
		goto out_clocks;
	ret = wcd_wdsp_load_class(wdsp, fw, ehdr, false);
	if (ret)
		goto out_clocks;

	wcd_wdsp_codec_clocks_disable(wdsp);
	ret = wcd_wdsp_clock_disable(wdsp);
	if (ret)
		goto out_fw;

	ret = wcd_wdsp_clock_enable(wdsp);
	if (ret)
		goto out_fw;
	ret = wcd_wdsp_codec_clocks_enable(wdsp);
	if (ret)
		goto out_fw;
	ret = wcd_wdsp_memory_enable(wdsp, true);
	if (ret)
		goto out_clocks;
	ret = wcd_wdsp_load_class(wdsp, fw, ehdr, true);
	if (ret)
		goto out_clocks;

	regmap_update_bits(map, WCD934X_CPE_SS_WDOG_CFG, 0x3f, 0x21);
	regmap_write(map, WCD934X_CPE_SS_SS_ERROR_INT_CLEAR_0A, 0xff);
	regmap_write(map, WCD934X_CPE_SS_SS_ERROR_INT_CLEAR_0B, 0xff);
	reinit_completion(&wdsp->boot_done);
	regmap_update_bits(map, WCD934X_CPE_SS_CPE_CTL, 0x02, 0x02);

	timeout = wait_for_completion_timeout(&wdsp->boot_done,
			msecs_to_jiffies(WCD_WDSP_BOOT_TIMEOUT_MS));
	if (!timeout) {
		dev_err(&wdsp->spi->dev, "WDSP IPC1 boot timeout\n");
		ret = -ETIMEDOUT;
		regmap_update_bits(map, WCD934X_CPE_SS_CPE_CTL, 0x02, 0x00);
		goto out_clocks;
	}

	regmap_update_bits(map, WCD934X_CPE_SS_WDOG_CFG, 0x10, 0x10);
	wdsp->booted = true;
	dev_info(&wdsp->spi->dev,
		 "WDSP booted (entry %#x, firmware %s)\n",
		 ehdr->e_entry, wdsp->firmware_name);
	release_firmware(fw);
	return 0;

out_clocks:
	wcd_wdsp_codec_clocks_disable(wdsp);
out_fw:
	release_firmware(fw);
	return ret;
}

static ssize_t boot_status_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	struct wcd934x_wdsp *wdsp = spi_get_drvdata(to_spi_device(dev));

	return sysfs_emit(buf, "%s result=%d clock=%s\n",
			  wdsp->booted ? "booted" : "not-booted",
			  wdsp->boot_result,
			  wdsp->clock_on ? "on" : "off");
}
static DEVICE_ATTR_RO(boot_status);

static long wcd_wdsp_ioctl(struct file *file, unsigned int cmd,
			   unsigned long arg)
{
	struct miscdevice *miscdev = file->private_data;
	struct wcd934x_wdsp *wdsp =
		container_of(miscdev, struct wcd934x_wdsp, miscdev);
	struct wcd934x_wdsp_xfer xfer;
	void __user *user_data;
	u8 *data;
	int ret;

	if (cmd != WCD934X_WDSP_IOC_MEM_READ &&
	    cmd != WCD934X_WDSP_IOC_MEM_WRITE)
		return -ENOTTY;
	if (!wdsp->booted)
		return -ENODEV;
	if (copy_from_user(&xfer, (void __user *)arg, sizeof(xfer)))
		return -EFAULT;
	if (!xfer.len || xfer.len > WCD_WDSP_USER_XFER_MAX ||
	    !IS_ALIGNED(xfer.remote_addr, sizeof(u32)) ||
	    !IS_ALIGNED(xfer.len, sizeof(u32)) ||
	    xfer.remote_addr > WCD_SPI_ADDR_MASK ||
	    xfer.len > WCD_SPI_ADDR_MASK - xfer.remote_addr + 1)
		return -EINVAL;

	user_data = u64_to_user_ptr(xfer.data);
	if (cmd == WCD934X_WDSP_IOC_MEM_WRITE) {
		data = memdup_user(user_data, xfer.len);
		if (IS_ERR(data))
			return PTR_ERR(data);
	} else {
		data = kzalloc(xfer.len, GFP_KERNEL);
		if (!data)
			return -ENOMEM;
	}

	if (cmd == WCD934X_WDSP_IOC_MEM_WRITE) {
		ret = wcd_wdsp_mem_write(wdsp, xfer.remote_addr,
					 data, xfer.len);
	} else {
		ret = wcd_wdsp_mem_read(wdsp, xfer.remote_addr,
					data, xfer.len);
		if (!ret && copy_to_user(user_data, data, xfer.len))
			ret = -EFAULT;
	}

	kfree(data);
	return ret;
}

static const struct file_operations wcd_wdsp_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = wcd_wdsp_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = compat_ptr_ioctl,
#endif
	.llseek = noop_llseek,
};

static int wcd_wdsp_find_codec(struct wcd934x_wdsp *wdsp)
{
	struct device_node *np;

	np = of_parse_phandle(wdsp->spi->dev.of_node, "qcom,wcd934x", 0);
	if (!np)
		return -EINVAL;

	wdsp->codec_dev = bus_find_device_by_of_node(&slimbus_bus, np);
	of_node_put(np);
	if (!wdsp->codec_dev)
		return -EPROBE_DEFER;

	wdsp->codec = dev_get_drvdata(wdsp->codec_dev);
	if (!wdsp->codec || !wdsp->codec->regmap ||
	    !wdsp->codec->extclk || !wdsp->codec->irq_data) {
		put_device(wdsp->codec_dev);
		wdsp->codec_dev = NULL;
		wdsp->codec = NULL;
		return -EPROBE_DEFER;
	}

	return 0;
}

static int wcd_wdsp_probe(struct spi_device *spi)
{
	struct wcd934x_wdsp *wdsp;
	int ret;

	wdsp = devm_kzalloc(&spi->dev, sizeof(*wdsp), GFP_KERNEL);
	if (!wdsp)
		return -ENOMEM;

	wdsp->spi = spi;
	wdsp->mem_base = 0x100000;
	of_property_read_u32(spi->dev.of_node, "qcom,mem-base-addr",
			     &wdsp->mem_base);
	ret = of_property_read_string(spi->dev.of_node, "firmware-name",
				      &wdsp->firmware_name);
	if (ret)
		wdsp->firmware_name =
			"qcom/msft/surface/pro-x-sq2/qcwdsp8180.mbn";

	init_completion(&wdsp->boot_done);
	mutex_init(&wdsp->xfer_lock);
	spi_set_drvdata(spi, wdsp);

	ret = wcd_wdsp_find_codec(wdsp);
	if (ret)
		return dev_err_probe(&spi->dev, ret, "WCD934x codec not ready\n");

	wdsp->ipc_irq = regmap_irq_get_virq(wdsp->codec->irq_data,
					    WCD934X_IRQ_CPE1_INTR);
	if (wdsp->ipc_irq < 0) {
		ret = wdsp->ipc_irq;
		goto out_put;
	}
	ret = devm_request_threaded_irq(&spi->dev, wdsp->ipc_irq, NULL,
					wcd_wdsp_ipc_irq, IRQF_ONESHOT,
					"wcd9340-wdsp-ipc1", wdsp);
	if (ret)
		goto out_put;

	wdsp->err_irq = regmap_irq_get_virq(wdsp->codec->irq_data,
					    WCD934X_IRQ_CPE_ERROR);
	if (wdsp->err_irq >= 0) {
		ret = devm_request_threaded_irq(&spi->dev, wdsp->err_irq, NULL,
						wcd_wdsp_error_irq, IRQF_ONESHOT,
						"wcd9340-wdsp-error", wdsp);
		if (ret)
			dev_warn(&spi->dev, "cannot request WDSP error IRQ: %d\n",
				 ret);
	}

	ret = device_create_file(&spi->dev, &dev_attr_boot_status);
	if (ret)
		goto out_put;

	wdsp->boot_result = wcd_wdsp_boot(wdsp);
	if (wdsp->boot_result) {
		ret = wdsp->boot_result;
		device_remove_file(&spi->dev, &dev_attr_boot_status);
		goto out_put;
	}

	wdsp->miscdev.minor = MISC_DYNAMIC_MINOR;
	wdsp->miscdev.name = "wcd9340-wdsp";
	wdsp->miscdev.fops = &wcd_wdsp_fops;
	wdsp->miscdev.parent = &spi->dev;
	wdsp->miscdev.mode = 0600;
	ret = misc_register(&wdsp->miscdev);
	if (ret) {
		device_remove_file(&spi->dev, &dev_attr_boot_status);
		goto out_put;
	}

	return 0;
out_put:
	put_device(wdsp->codec_dev);
	wdsp->codec_dev = NULL;
	return ret;
}

static void wcd_wdsp_remove(struct spi_device *spi)
{
	struct wcd934x_wdsp *wdsp = spi_get_drvdata(spi);

	misc_deregister(&wdsp->miscdev);
	device_remove_file(&spi->dev, &dev_attr_boot_status);
	if (wdsp->booted) {
		regmap_update_bits(wdsp->codec->regmap, WCD934X_CPE_SS_WDOG_CFG,
				   0x3f, 0x01);
		regmap_update_bits(wdsp->codec->regmap, WCD934X_CPE_SS_CPE_CTL,
				   0x02, 0x00);
		wcd_wdsp_codec_clocks_disable(wdsp);
	}
	wcd_wdsp_clock_disable(wdsp);
	put_device(wdsp->codec_dev);
}

static const struct of_device_id wcd_wdsp_of_match[] = {
	{ .compatible = "qcom,wcd9340-wdsp-spi" },
	{}
};
MODULE_DEVICE_TABLE(of, wcd_wdsp_of_match);

static struct spi_driver wcd_wdsp_driver = {
	.probe = wcd_wdsp_probe,
	.remove = wcd_wdsp_remove,
	.driver = {
		.name = "wcd9340-wdsp",
		.of_match_table = wcd_wdsp_of_match,
	},
};
module_spi_driver(wcd_wdsp_driver);

MODULE_DESCRIPTION("Qualcomm WCD9340 WDSP firmware loader over AUDD SPI");
MODULE_LICENSE("GPL");
