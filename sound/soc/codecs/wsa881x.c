// SPDX-License-Identifier: GPL-2.0
// Copyright (c) 2015-2017, The Linux Foundation.
// Copyright (c) 2019, Linaro Limited

#include <linux/bitops.h>
#include <linux/gpio.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/pm_runtime.h>
#include <linux/soundwire/sdw.h>
#include <linux/soundwire/sdw_registers.h>
#include <linux/soundwire/sdw_type.h>
#include <sound/soc.h>
#include <sound/tlv.h>

#define WSA881X_DIGITAL_BASE		0x3000
#define WSA881X_ANALOG_BASE		0x3100

/* Digital register address space */
#define WSA881X_CHIP_ID0			(WSA881X_DIGITAL_BASE + 0x0000)
#define WSA881X_CHIP_ID1			(WSA881X_DIGITAL_BASE + 0x0001)
#define WSA881X_CHIP_ID2			(WSA881X_DIGITAL_BASE + 0x0002)
#define WSA881X_CHIP_ID3			(WSA881X_DIGITAL_BASE + 0x0003)
#define WSA881X_BUS_ID				(WSA881X_DIGITAL_BASE + 0x0004)
#define WSA881X_CDC_RST_CTL			(WSA881X_DIGITAL_BASE + 0x0005)
#define WSA881X_CDC_TOP_CLK_CTL			(WSA881X_DIGITAL_BASE + 0x0006)
#define WSA881X_CDC_ANA_CLK_CTL			(WSA881X_DIGITAL_BASE + 0x0007)
#define WSA881X_CDC_DIG_CLK_CTL			(WSA881X_DIGITAL_BASE + 0x0008)
#define WSA881X_CLOCK_CONFIG			(WSA881X_DIGITAL_BASE + 0x0009)
#define WSA881X_ANA_CTL				(WSA881X_DIGITAL_BASE + 0x000A)
#define WSA881X_SWR_RESET_EN			(WSA881X_DIGITAL_BASE + 0x000B)
#define WSA881X_RESET_CTL			(WSA881X_DIGITAL_BASE + 0x000C)
#define WSA881X_TADC_VALUE_CTL			(WSA881X_DIGITAL_BASE + 0x000F)
#define WSA881X_TEMP_DETECT_CTL			(WSA881X_DIGITAL_BASE + 0x0010)
#define WSA881X_TEMP_MSB			(WSA881X_DIGITAL_BASE + 0x0011)
#define WSA881X_TEMP_LSB			(WSA881X_DIGITAL_BASE + 0x0012)
#define WSA881X_TEMP_CONFIG0			(WSA881X_DIGITAL_BASE + 0x0013)
#define WSA881X_TEMP_CONFIG1			(WSA881X_DIGITAL_BASE + 0x0014)
#define WSA881X_CDC_CLIP_CTL			(WSA881X_DIGITAL_BASE + 0x0015)
#define WSA881X_SDM_PDM9_LSB			(WSA881X_DIGITAL_BASE + 0x0016)
#define WSA881X_SDM_PDM9_MSB			(WSA881X_DIGITAL_BASE + 0x0017)
#define WSA881X_CDC_RX_CTL			(WSA881X_DIGITAL_BASE + 0x0018)
#define WSA881X_DEM_BYPASS_DATA0		(WSA881X_DIGITAL_BASE + 0x0019)
#define WSA881X_DEM_BYPASS_DATA1		(WSA881X_DIGITAL_BASE + 0x001A)
#define WSA881X_DEM_BYPASS_DATA2		(WSA881X_DIGITAL_BASE + 0x001B)
#define WSA881X_DEM_BYPASS_DATA3		(WSA881X_DIGITAL_BASE + 0x001C)
#define WSA881X_OTP_CTRL0			(WSA881X_DIGITAL_BASE + 0x001D)
#define WSA881X_OTP_CTRL1			(WSA881X_DIGITAL_BASE + 0x001E)
#define WSA881X_HDRIVE_CTL_GROUP1		(WSA881X_DIGITAL_BASE + 0x001F)
#define WSA881X_INTR_MODE			(WSA881X_DIGITAL_BASE + 0x0020)
#define WSA881X_INTR_MASK			(WSA881X_DIGITAL_BASE + 0x0021)
#define WSA881X_INTR_STATUS			(WSA881X_DIGITAL_BASE + 0x0022)
#define WSA881X_INTR_CLEAR			(WSA881X_DIGITAL_BASE + 0x0023)
#define WSA881X_INTR_LEVEL			(WSA881X_DIGITAL_BASE + 0x0024)
#define WSA881X_INTR_SET			(WSA881X_DIGITAL_BASE + 0x0025)
#define WSA881X_INTR_TEST			(WSA881X_DIGITAL_BASE + 0x0026)
#define WSA881X_PDM_TEST_MODE			(WSA881X_DIGITAL_BASE + 0x0030)
#define WSA881X_ATE_TEST_MODE			(WSA881X_DIGITAL_BASE + 0x0031)
#define WSA881X_PIN_CTL_MODE			(WSA881X_DIGITAL_BASE + 0x0032)
#define WSA881X_PIN_CTL_OE			(WSA881X_DIGITAL_BASE + 0x0033)
#define WSA881X_PIN_WDATA_IOPAD			(WSA881X_DIGITAL_BASE + 0x0034)
#define WSA881X_PIN_STATUS			(WSA881X_DIGITAL_BASE + 0x0035)
#define WSA881X_DIG_DEBUG_MODE			(WSA881X_DIGITAL_BASE + 0x0037)
#define WSA881X_DIG_DEBUG_SEL			(WSA881X_DIGITAL_BASE + 0x0038)
#define WSA881X_DIG_DEBUG_EN			(WSA881X_DIGITAL_BASE + 0x0039)
#define WSA881X_SWR_HM_TEST1			(WSA881X_DIGITAL_BASE + 0x003B)
#define WSA881X_SWR_HM_TEST2			(WSA881X_DIGITAL_BASE + 0x003C)
#define WSA881X_TEMP_DETECT_DBG_CTL		(WSA881X_DIGITAL_BASE + 0x003D)
#define WSA881X_TEMP_DEBUG_MSB			(WSA881X_DIGITAL_BASE + 0x003E)
#define WSA881X_TEMP_DEBUG_LSB			(WSA881X_DIGITAL_BASE + 0x003F)
#define WSA881X_SAMPLE_EDGE_SEL			(WSA881X_DIGITAL_BASE + 0x0044)
#define WSA881X_IOPAD_CTL			(WSA881X_DIGITAL_BASE + 0x0045)
#define WSA881X_SPARE_0				(WSA881X_DIGITAL_BASE + 0x0050)
#define WSA881X_SPARE_1				(WSA881X_DIGITAL_BASE + 0x0051)
#define WSA881X_SPARE_2				(WSA881X_DIGITAL_BASE + 0x0052)
#define WSA881X_OTP_REG_0			(WSA881X_DIGITAL_BASE + 0x0080)
#define WSA881X_OTP_REG_1			(WSA881X_DIGITAL_BASE + 0x0081)
#define WSA881X_OTP_REG_2			(WSA881X_DIGITAL_BASE + 0x0082)
#define WSA881X_OTP_REG_3			(WSA881X_DIGITAL_BASE + 0x0083)
#define WSA881X_OTP_REG_4			(WSA881X_DIGITAL_BASE + 0x0084)
#define WSA881X_OTP_REG_5			(WSA881X_DIGITAL_BASE + 0x0085)
#define WSA881X_OTP_REG_6			(WSA881X_DIGITAL_BASE + 0x0086)
#define WSA881X_OTP_REG_7			(WSA881X_DIGITAL_BASE + 0x0087)
#define WSA881X_OTP_REG_8			(WSA881X_DIGITAL_BASE + 0x0088)
#define WSA881X_OTP_REG_9			(WSA881X_DIGITAL_BASE + 0x0089)
#define WSA881X_OTP_REG_10			(WSA881X_DIGITAL_BASE + 0x008A)
#define WSA881X_OTP_REG_11			(WSA881X_DIGITAL_BASE + 0x008B)
#define WSA881X_OTP_REG_12			(WSA881X_DIGITAL_BASE + 0x008C)
#define WSA881X_OTP_REG_13			(WSA881X_DIGITAL_BASE + 0x008D)
#define WSA881X_OTP_REG_14			(WSA881X_DIGITAL_BASE + 0x008E)
#define WSA881X_OTP_REG_15			(WSA881X_DIGITAL_BASE + 0x008F)
#define WSA881X_OTP_REG_16			(WSA881X_DIGITAL_BASE + 0x0090)
#define WSA881X_OTP_REG_17			(WSA881X_DIGITAL_BASE + 0x0091)
#define WSA881X_OTP_REG_18			(WSA881X_DIGITAL_BASE + 0x0092)
#define WSA881X_OTP_REG_19			(WSA881X_DIGITAL_BASE + 0x0093)
#define WSA881X_OTP_REG_20			(WSA881X_DIGITAL_BASE + 0x0094)
#define WSA881X_OTP_REG_21			(WSA881X_DIGITAL_BASE + 0x0095)
#define WSA881X_OTP_REG_22			(WSA881X_DIGITAL_BASE + 0x0096)
#define WSA881X_OTP_REG_23			(WSA881X_DIGITAL_BASE + 0x0097)
#define WSA881X_OTP_REG_24			(WSA881X_DIGITAL_BASE + 0x0098)
#define WSA881X_OTP_REG_25			(WSA881X_DIGITAL_BASE + 0x0099)
#define WSA881X_OTP_REG_26			(WSA881X_DIGITAL_BASE + 0x009A)
#define WSA881X_OTP_REG_27			(WSA881X_DIGITAL_BASE + 0x009B)
#define WSA881X_OTP_REG_28			(WSA881X_DIGITAL_BASE + 0x009C)
#define WSA881X_OTP_REG_29			(WSA881X_DIGITAL_BASE + 0x009D)
#define WSA881X_OTP_REG_30			(WSA881X_DIGITAL_BASE + 0x009E)
#define WSA881X_OTP_REG_31			(WSA881X_DIGITAL_BASE + 0x009F)
#define WSA881X_OTP_REG_63			(WSA881X_DIGITAL_BASE + 0x00BF)

/* Analog Register address space */
#define WSA881X_BIAS_REF_CTRL			(WSA881X_ANALOG_BASE + 0x0000)
#define WSA881X_BIAS_TEST			(WSA881X_ANALOG_BASE + 0x0001)
#define WSA881X_BIAS_BIAS			(WSA881X_ANALOG_BASE + 0x0002)
#define WSA881X_TEMP_OP				(WSA881X_ANALOG_BASE + 0x0003)
#define WSA881X_TEMP_IREF_CTRL			(WSA881X_ANALOG_BASE + 0x0004)
#define WSA881X_TEMP_ISENS_CTRL			(WSA881X_ANALOG_BASE + 0x0005)
#define WSA881X_TEMP_CLK_CTRL			(WSA881X_ANALOG_BASE + 0x0006)
#define WSA881X_TEMP_TEST			(WSA881X_ANALOG_BASE + 0x0007)
#define WSA881X_TEMP_BIAS			(WSA881X_ANALOG_BASE + 0x0008)
#define WSA881X_TEMP_ADC_CTRL			(WSA881X_ANALOG_BASE + 0x0009)
#define WSA881X_TEMP_DOUT_MSB			(WSA881X_ANALOG_BASE + 0x000A)
#define WSA881X_TEMP_DOUT_LSB			(WSA881X_ANALOG_BASE + 0x000B)
#define WSA881X_ADC_EN_MODU_V			(WSA881X_ANALOG_BASE + 0x0010)
#define WSA881X_ADC_EN_MODU_I			(WSA881X_ANALOG_BASE + 0x0011)
#define WSA881X_ADC_EN_DET_TEST_V		(WSA881X_ANALOG_BASE + 0x0012)
#define WSA881X_ADC_EN_DET_TEST_I		(WSA881X_ANALOG_BASE + 0x0013)
#define WSA881X_ADC_SEL_IBIAS			(WSA881X_ANALOG_BASE + 0x0014)
#define WSA881X_ADC_EN_SEL_IBAIS		(WSA881X_ANALOG_BASE + 0x0015)
#define WSA881X_SPKR_DRV_EN			(WSA881X_ANALOG_BASE + 0x001A)
#define WSA881X_SPKR_DRV_GAIN			(WSA881X_ANALOG_BASE + 0x001B)
#define WSA881X_PA_GAIN_SEL_MASK		BIT(3)
#define WSA881X_PA_GAIN_SEL_REG			BIT(3)
#define WSA881X_PA_GAIN_SEL_DRE			0
#define WSA881X_PA_PWM_FREQ_MASK		BIT(2)
#define WSA881X_PA_PWM_FREQ_600KHZ		BIT(2)
#define WSA881X_SPKR_PAG_GAIN_MASK		GENMASK(7, 4)
#define WSA881X_SPKR_DAC_CTL			(WSA881X_ANALOG_BASE + 0x001C)
#define WSA881X_SPKR_DRV_DBG			(WSA881X_ANALOG_BASE + 0x001D)
#define WSA881X_SPKR_PWRSTG_DBG			(WSA881X_ANALOG_BASE + 0x001E)
#define WSA881X_SPKR_OCP_CTL			(WSA881X_ANALOG_BASE + 0x001F)
#define WSA881X_SPKR_OCP_MASK			GENMASK(7, 6)
#define WSA881X_SPKR_OCP_EN			BIT(7)
#define WSA881X_SPKR_OCP_HOLD			BIT(6)
#define WSA881X_SPKR_CLIP_CTL			(WSA881X_ANALOG_BASE + 0x0020)
#define WSA881X_SPKR_BBM_CTL			(WSA881X_ANALOG_BASE + 0x0021)
#define WSA881X_SPKR_MISC_CTL1			(WSA881X_ANALOG_BASE + 0x0022)
#define WSA881X_SPKR_MISC_CTL2			(WSA881X_ANALOG_BASE + 0x0023)
#define WSA881X_SPKR_BIAS_INT			(WSA881X_ANALOG_BASE + 0x0024)
#define WSA881X_SPKR_PA_INT			(WSA881X_ANALOG_BASE + 0x0025)
#define WSA881X_SPKR_BIAS_CAL			(WSA881X_ANALOG_BASE + 0x0026)
#define WSA881X_SPKR_BIAS_PSRR			(WSA881X_ANALOG_BASE + 0x0027)
#define WSA881X_SPKR_STATUS1			(WSA881X_ANALOG_BASE + 0x0028)
#define WSA881X_SPKR_STATUS2			(WSA881X_ANALOG_BASE + 0x0029)
#define WSA881X_BOOST_EN_CTL			(WSA881X_ANALOG_BASE + 0x002A)
#define WSA881X_BOOST_EN_MASK			BIT(7)
#define WSA881X_BOOST_EN			BIT(7)
#define WSA881X_BOOST_CURRENT_LIMIT		(WSA881X_ANALOG_BASE + 0x002B)
#define WSA881X_BOOST_PS_CTL			(WSA881X_ANALOG_BASE + 0x002C)
#define WSA881X_BOOST_PRESET_OUT1		(WSA881X_ANALOG_BASE + 0x002D)
#define WSA881X_BOOST_PRESET_OUT2		(WSA881X_ANALOG_BASE + 0x002E)
#define WSA881X_BOOST_FORCE_OUT			(WSA881X_ANALOG_BASE + 0x002F)
#define WSA881X_BOOST_LDO_PROG			(WSA881X_ANALOG_BASE + 0x0030)
#define WSA881X_BOOST_SLOPE_COMP_ISENSE_FB	(WSA881X_ANALOG_BASE + 0x0031)
#define WSA881X_BOOST_RON_CTL			(WSA881X_ANALOG_BASE + 0x0032)
#define WSA881X_BOOST_LOOP_STABILITY		(WSA881X_ANALOG_BASE + 0x0033)
#define WSA881X_BOOST_ZX_CTL			(WSA881X_ANALOG_BASE + 0x0034)
#define WSA881X_BOOST_START_CTL			(WSA881X_ANALOG_BASE + 0x0035)
#define WSA881X_BOOST_MISC1_CTL			(WSA881X_ANALOG_BASE + 0x0036)
#define WSA881X_BOOST_MISC2_CTL			(WSA881X_ANALOG_BASE + 0x0037)
#define WSA881X_BOOST_MISC3_CTL			(WSA881X_ANALOG_BASE + 0x0038)
#define WSA881X_BOOST_ATEST_CTL			(WSA881X_ANALOG_BASE + 0x0039)
#define WSA881X_SPKR_PROT_FE_GAIN		(WSA881X_ANALOG_BASE + 0x003A)
#define WSA881X_SPKR_PROT_FE_CM_LDO_SET		(WSA881X_ANALOG_BASE + 0x003B)
#define WSA881X_SPKR_PROT_FE_ISENSE_BIAS_SET1	(WSA881X_ANALOG_BASE + 0x003C)
#define WSA881X_SPKR_PROT_FE_ISENSE_BIAS_SET2	(WSA881X_ANALOG_BASE + 0x003D)
#define WSA881X_SPKR_PROT_ATEST1		(WSA881X_ANALOG_BASE + 0x003E)
#define WSA881X_SPKR_PROT_ATEST2		(WSA881X_ANALOG_BASE + 0x003F)
#define WSA881X_SPKR_PROT_FE_VSENSE_VCM		(WSA881X_ANALOG_BASE + 0x0040)
#define WSA881X_SPKR_PROT_FE_VSENSE_BIAS_SET1	(WSA881X_ANALOG_BASE + 0x0041)
#define WSA881X_BONGO_RESRV_REG1		(WSA881X_ANALOG_BASE + 0x0042)
#define WSA881X_BONGO_RESRV_REG2		(WSA881X_ANALOG_BASE + 0x0043)
#define WSA881X_SPKR_PROT_SAR			(WSA881X_ANALOG_BASE + 0x0044)
#define WSA881X_SPKR_STATUS3			(WSA881X_ANALOG_BASE + 0x0045)

#define SWRS_SCP_FRAME_CTRL_BANK(m)		(0x60 + 0x10 * (m))
#define SWRS_SCP_HOST_CLK_DIV2_CTL_BANK(m)	(0xE0 + 0x10 * (m))
#define SWR_SLV_MAX_REG_ADDR	0x390
#define SWR_SLV_START_REG_ADDR	0x40
#define SWR_SLV_MAX_BUF_LEN	20
#define BYTES_PER_LINE		12
#define SWR_SLV_RD_BUF_LEN	8
#define SWR_SLV_WR_BUF_LEN	32
#define SWR_SLV_MAX_DEVICES	2
#define WSA881X_MAX_SWR_PORTS   4
#define WSA881X_VERSION_ENTRY_SIZE 27
#define WSA881X_OCP_CTL_TIMER_SEC 2
#define WSA881X_OCP_CTL_TEMP_CELSIUS 25
#define WSA881X_OCP_CTL_POLL_TIMER_SEC 60
#define WSA881X_PROBE_TIMEOUT 1000

#define WSA881X_PA_GAIN_TLV(xname, reg, shift, max, invert, tlv_array) \
	SOC_SINGLE_EXT_TLV(xname, reg, shift, max, invert, \
			   wsa881x_get_pa_gain, wsa881x_put_pa_gain, tlv_array)

static const struct reg_default wsa881x_defaults[] = {
	{ WSA881X_CHIP_ID0, 0x00 },
	{ WSA881X_CHIP_ID1, 0x00 },
	{ WSA881X_CHIP_ID2, 0x00 },
	{ WSA881X_CHIP_ID3, 0x02 },
	{ WSA881X_BUS_ID, 0x00 },
	{ WSA881X_CDC_RST_CTL, 0x00 },
	{ WSA881X_CDC_TOP_CLK_CTL, 0x03 },
	{ WSA881X_CDC_ANA_CLK_CTL, 0x00 },
	{ WSA881X_CDC_DIG_CLK_CTL, 0x00 },
	{ WSA881X_CLOCK_CONFIG, 0x00 },
	{ WSA881X_ANA_CTL, 0x08 },
	{ WSA881X_SWR_RESET_EN, 0x00 },
	{ WSA881X_TEMP_DETECT_CTL, 0x01 },
	{ WSA881X_TEMP_MSB, 0x00 },
	{ WSA881X_TEMP_LSB, 0x00 },
	{ WSA881X_TEMP_CONFIG0, 0x00 },
	{ WSA881X_TEMP_CONFIG1, 0x00 },
	{ WSA881X_CDC_CLIP_CTL, 0x03 },
	{ WSA881X_SDM_PDM9_LSB, 0x00 },
	{ WSA881X_SDM_PDM9_MSB, 0x00 },
	{ WSA881X_CDC_RX_CTL, 0x7E },
	{ WSA881X_DEM_BYPASS_DATA0, 0x00 },
	{ WSA881X_DEM_BYPASS_DATA1, 0x00 },
	{ WSA881X_DEM_BYPASS_DATA2, 0x00 },
	{ WSA881X_DEM_BYPASS_DATA3, 0x00 },
	{ WSA881X_OTP_CTRL0, 0x00 },
	{ WSA881X_OTP_CTRL1, 0x00 },
	{ WSA881X_HDRIVE_CTL_GROUP1, 0x00 },
	{ WSA881X_INTR_MODE, 0x00 },
	{ WSA881X_INTR_STATUS, 0x00 },
	{ WSA881X_INTR_CLEAR, 0x00 },
	{ WSA881X_INTR_LEVEL, 0x00 },
	{ WSA881X_INTR_SET, 0x00 },
	{ WSA881X_INTR_TEST, 0x00 },
	{ WSA881X_PDM_TEST_MODE, 0x00 },
	{ WSA881X_ATE_TEST_MODE, 0x00 },
	{ WSA881X_PIN_CTL_MODE, 0x00 },
	{ WSA881X_PIN_CTL_OE, 0x00 },
	{ WSA881X_PIN_WDATA_IOPAD, 0x00 },
	{ WSA881X_PIN_STATUS, 0x00 },
	{ WSA881X_DIG_DEBUG_MODE, 0x00 },
	{ WSA881X_DIG_DEBUG_SEL, 0x00 },
	{ WSA881X_DIG_DEBUG_EN, 0x00 },
	{ WSA881X_SWR_HM_TEST1, 0x08 },
	{ WSA881X_SWR_HM_TEST2, 0x00 },
	{ WSA881X_TEMP_DETECT_DBG_CTL, 0x00 },
	{ WSA881X_TEMP_DEBUG_MSB, 0x00 },
	{ WSA881X_TEMP_DEBUG_LSB, 0x00 },
	{ WSA881X_SAMPLE_EDGE_SEL, 0x0C },
	{ WSA881X_SPARE_0, 0x00 },
	{ WSA881X_SPARE_1, 0x00 },
	{ WSA881X_SPARE_2, 0x00 },
	{ WSA881X_OTP_REG_0, 0x01 },
	{ WSA881X_OTP_REG_1, 0xFF },
	{ WSA881X_OTP_REG_2, 0xC0 },
	{ WSA881X_OTP_REG_3, 0xFF },
	{ WSA881X_OTP_REG_4, 0xC0 },
	{ WSA881X_OTP_REG_5, 0xFF },
	{ WSA881X_OTP_REG_6, 0xFF },
	{ WSA881X_OTP_REG_7, 0xFF },
	{ WSA881X_OTP_REG_8, 0xFF },
	{ WSA881X_OTP_REG_9, 0xFF },
	{ WSA881X_OTP_REG_10, 0xFF },
	{ WSA881X_OTP_REG_11, 0xFF },
	{ WSA881X_OTP_REG_12, 0xFF },
	{ WSA881X_OTP_REG_13, 0xFF },
	{ WSA881X_OTP_REG_14, 0xFF },
	{ WSA881X_OTP_REG_15, 0xFF },
	{ WSA881X_OTP_REG_16, 0xFF },
	{ WSA881X_OTP_REG_17, 0xFF },
	{ WSA881X_OTP_REG_18, 0xFF },
	{ WSA881X_OTP_REG_19, 0xFF },
	{ WSA881X_OTP_REG_20, 0xFF },
	{ WSA881X_OTP_REG_21, 0xFF },
	{ WSA881X_OTP_REG_22, 0xFF },
	{ WSA881X_OTP_REG_23, 0xFF },
	{ WSA881X_OTP_REG_24, 0x03 },
	{ WSA881X_OTP_REG_25, 0x01 },
	{ WSA881X_OTP_REG_26, 0x03 },
	{ WSA881X_OTP_REG_27, 0x11 },
	{ WSA881X_OTP_REG_63, 0x40 },
	/* WSA881x Analog registers */
	{ WSA881X_BIAS_REF_CTRL, 0x6C },
	{ WSA881X_BIAS_TEST, 0x16 },
	{ WSA881X_BIAS_BIAS, 0xF0 },
	{ WSA881X_TEMP_OP, 0x00 },
	{ WSA881X_TEMP_IREF_CTRL, 0x56 },
	{ WSA881X_TEMP_ISENS_CTRL, 0x47 },
	{ WSA881X_TEMP_CLK_CTRL, 0x87 },
	{ WSA881X_TEMP_TEST, 0x00 },
	{ WSA881X_TEMP_BIAS, 0x51 },
	{ WSA881X_TEMP_DOUT_MSB, 0x00 },
	{ WSA881X_TEMP_DOUT_LSB, 0x00 },
	{ WSA881X_ADC_EN_MODU_V, 0x00 },
	{ WSA881X_ADC_EN_MODU_I, 0x00 },
	{ WSA881X_ADC_EN_DET_TEST_V, 0x00 },
	{ WSA881X_ADC_EN_DET_TEST_I, 0x00 },
	{ WSA881X_ADC_EN_SEL_IBAIS, 0x10 },
	{ WSA881X_SPKR_DRV_EN, 0x74 },
	{ WSA881X_SPKR_DRV_DBG, 0x15 },
	{ WSA881X_SPKR_PWRSTG_DBG, 0x00 },
	{ WSA881X_SPKR_OCP_CTL, 0xD4 },
	{ WSA881X_SPKR_CLIP_CTL, 0x90 },
	{ WSA881X_SPKR_PA_INT, 0x54 },
	{ WSA881X_SPKR_BIAS_CAL, 0xAC },
	{ WSA881X_SPKR_STATUS1, 0x00 },
	{ WSA881X_SPKR_STATUS2, 0x00 },
	{ WSA881X_BOOST_EN_CTL, 0x18 },
	{ WSA881X_BOOST_CURRENT_LIMIT, 0x7A },
	{ WSA881X_BOOST_PRESET_OUT2, 0x70 },
	{ WSA881X_BOOST_FORCE_OUT, 0x0E },
	{ WSA881X_BOOST_LDO_PROG, 0x16 },
	{ WSA881X_BOOST_SLOPE_COMP_ISENSE_FB, 0x71 },
	{ WSA881X_BOOST_RON_CTL, 0x0F },
	{ WSA881X_BOOST_ZX_CTL, 0x34 },
	{ WSA881X_BOOST_START_CTL, 0x23 },
	{ WSA881X_BOOST_MISC1_CTL, 0x80 },
	{ WSA881X_BOOST_MISC2_CTL, 0x00 },
	{ WSA881X_BOOST_MISC3_CTL, 0x00 },
	{ WSA881X_BOOST_ATEST_CTL, 0x00 },
	{ WSA881X_SPKR_PROT_FE_GAIN, 0x46 },
	{ WSA881X_SPKR_PROT_FE_CM_LDO_SET, 0x3B },
	{ WSA881X_SPKR_PROT_FE_ISENSE_BIAS_SET1, 0x8D },
	{ WSA881X_SPKR_PROT_FE_ISENSE_BIAS_SET2, 0x8D },
	{ WSA881X_SPKR_PROT_ATEST1, 0x01 },
	{ WSA881X_SPKR_PROT_FE_VSENSE_VCM, 0x8D },
	{ WSA881X_SPKR_PROT_FE_VSENSE_BIAS_SET1, 0x4D },
	{ WSA881X_SPKR_PROT_SAR, 0x00 },
	{ WSA881X_SPKR_STATUS3, 0x00 },
};

static const struct reg_sequence wsa881x_pre_pmu_pa_2_0[] = {
	{ WSA881X_SPKR_DRV_GAIN, 0x41, 0 },
	{ WSA881X_SPKR_MISC_CTL1, 0x87, 0 },
};

static const struct reg_sequence wsa881x_vi_txfe_en_2_0[] = {
	{ WSA881X_SPKR_PROT_FE_VSENSE_VCM, 0x85, 0 },
	{ WSA881X_SPKR_PROT_ATEST2, 0x0A, 0 },
	{ WSA881X_SPKR_PROT_FE_GAIN, 0x47, 0 },
};

/* Default register reset values for WSA881x rev 2.0 */
static const struct reg_sequence wsa881x_rev_2_0[] = {
	{ WSA881X_RESET_CTL, 0x00, 0x00 },
	{ WSA881X_TADC_VALUE_CTL, 0x01, 0x00 },
	{ WSA881X_INTR_MASK, 0x1B, 0x00 },
	{ WSA881X_IOPAD_CTL, 0x00, 0x00 },
	{ WSA881X_OTP_REG_28, 0x3F, 0x00 },
	{ WSA881X_OTP_REG_29, 0x3F, 0x00 },
	{ WSA881X_OTP_REG_30, 0x01, 0x00 },
	{ WSA881X_OTP_REG_31, 0x01, 0x00 },
	{ WSA881X_TEMP_ADC_CTRL, 0x03, 0x00 },
	{ WSA881X_ADC_SEL_IBIAS, 0x45, 0x00 },
	{ WSA881X_SPKR_DRV_GAIN, 0xC1, 0x00 },
	{ WSA881X_SPKR_DAC_CTL, 0x42, 0x00 },
	{ WSA881X_SPKR_BBM_CTL, 0x02, 0x00 },
	{ WSA881X_SPKR_MISC_CTL1, 0x40, 0x00 },
	{ WSA881X_SPKR_MISC_CTL2, 0x07, 0x00 },
	{ WSA881X_SPKR_BIAS_INT, 0x5F, 0x00 },
	{ WSA881X_SPKR_BIAS_PSRR, 0x44, 0x00 },
	{ WSA881X_BOOST_PS_CTL, 0xA0, 0x00 },
	{ WSA881X_BOOST_PRESET_OUT1, 0xB7, 0x00 },
	{ WSA881X_BOOST_LOOP_STABILITY, 0x8D, 0x00 },
	{ WSA881X_SPKR_PROT_ATEST2, 0x02, 0x00 },
	{ WSA881X_BONGO_RESRV_REG1, 0x5E, 0x00 },
	{ WSA881X_BONGO_RESRV_REG2, 0x07, 0x00 },
};

enum wsa_port_ids {
	WSA881X_PORT_DAC,
	WSA881X_PORT_COMP,
	WSA881X_PORT_BOOST,
	WSA881X_PORT_VISENSE,
};

/* 4 ports */
static struct sdw_dpn_prop wsa_sink_dpn_prop[WSA881X_MAX_SWR_PORTS] = {
	[WSA881X_PORT_DAC] = {
		.num = WSA881X_PORT_DAC + 1,
		.type = SDW_DPN_SIMPLE,
		.min_ch = 1,
		.max_ch = 1,
		.simple_ch_prep_sm = true,
		.read_only_wordlength = true,
	},
	[WSA881X_PORT_COMP] = {
		.num = WSA881X_PORT_COMP + 1,
		.type = SDW_DPN_SIMPLE,
		.min_ch = 1,
		.max_ch = 1,
		.simple_ch_prep_sm = true,
		.read_only_wordlength = true,
	},
	[WSA881X_PORT_BOOST] = {
		.num = WSA881X_PORT_BOOST + 1,
		.type = SDW_DPN_SIMPLE,
		.min_ch = 1,
		.max_ch = 1,
		.simple_ch_prep_sm = true,
		.read_only_wordlength = true,
	},
	[WSA881X_PORT_VISENSE] = {
		.num = WSA881X_PORT_VISENSE + 1,
		.type = SDW_DPN_SIMPLE,
		.min_ch = 1,
		.max_ch = 1,
		.simple_ch_prep_sm = true,
		.read_only_wordlength = true,
	}
};

static const struct sdw_port_config wsa881x_pconfig[WSA881X_MAX_SWR_PORTS] = {
	[WSA881X_PORT_DAC] = {
		.num = WSA881X_PORT_DAC + 1,
		.ch_mask = 0x1,
	},
	[WSA881X_PORT_COMP] = {
		.num = WSA881X_PORT_COMP + 1,
		.ch_mask = 0xf,
	},
	[WSA881X_PORT_BOOST] = {
		.num = WSA881X_PORT_BOOST + 1,
		.ch_mask = 0x3,
	},
	[WSA881X_PORT_VISENSE] = {
		.num = WSA881X_PORT_VISENSE + 1,
		.ch_mask = 0x3,
	},
};

static bool wsa881x_readable_register(struct device *dev, unsigned int reg)
{
	switch (reg) {
	case WSA881X_CHIP_ID0:
	case WSA881X_CHIP_ID1:
	case WSA881X_CHIP_ID2:
	case WSA881X_CHIP_ID3:
	case WSA881X_BUS_ID:
	case WSA881X_CDC_RST_CTL:
	case WSA881X_CDC_TOP_CLK_CTL:
	case WSA881X_CDC_ANA_CLK_CTL:
	case WSA881X_CDC_DIG_CLK_CTL:
	case WSA881X_CLOCK_CONFIG:
	case WSA881X_ANA_CTL:
	case WSA881X_SWR_RESET_EN:
	case WSA881X_RESET_CTL:
	case WSA881X_TADC_VALUE_CTL:
	case WSA881X_TEMP_DETECT_CTL:
	case WSA881X_TEMP_MSB:
	case WSA881X_TEMP_LSB:
	case WSA881X_TEMP_CONFIG0:
	case WSA881X_TEMP_CONFIG1:
	case WSA881X_CDC_CLIP_CTL:
	case WSA881X_SDM_PDM9_LSB:
	case WSA881X_SDM_PDM9_MSB:
	case WSA881X_CDC_RX_CTL:
	case WSA881X_DEM_BYPASS_DATA0:
	case WSA881X_DEM_BYPASS_DATA1:
	case WSA881X_DEM_BYPASS_DATA2:
	case WSA881X_DEM_BYPASS_DATA3:
	case WSA881X_OTP_CTRL0:
	case WSA881X_OTP_CTRL1:
	case WSA881X_HDRIVE_CTL_GROUP1:
	case WSA881X_INTR_MODE:
	case WSA881X_INTR_MASK:
	case WSA881X_INTR_STATUS:
	case WSA881X_INTR_CLEAR:
	case WSA881X_INTR_LEVEL:
	case WSA881X_INTR_SET:
	case WSA881X_INTR_TEST:
	case WSA881X_PDM_TEST_MODE:
	case WSA881X_ATE_TEST_MODE:
	case WSA881X_PIN_CTL_MODE:
	case WSA881X_PIN_CTL_OE:
	case WSA881X_PIN_WDATA_IOPAD:
	case WSA881X_PIN_STATUS:
	case WSA881X_DIG_DEBUG_MODE:
	case WSA881X_DIG_DEBUG_SEL:
	case WSA881X_DIG_DEBUG_EN:
	case WSA881X_SWR_HM_TEST1:
	case WSA881X_SWR_HM_TEST2:
	case WSA881X_TEMP_DETECT_DBG_CTL:
	case WSA881X_TEMP_DEBUG_MSB:
	case WSA881X_TEMP_DEBUG_LSB:
	case WSA881X_SAMPLE_EDGE_SEL:
	case WSA881X_IOPAD_CTL:
	case WSA881X_SPARE_0:
	case WSA881X_SPARE_1:
	case WSA881X_SPARE_2:
	case WSA881X_OTP_REG_0:
	case WSA881X_OTP_REG_1:
	case WSA881X_OTP_REG_2:
	case WSA881X_OTP_REG_3:
	case WSA881X_OTP_REG_4:
	case WSA881X_OTP_REG_5:
	case WSA881X_OTP_REG_6:
	case WSA881X_OTP_REG_7:
	case WSA881X_OTP_REG_8:
	case WSA881X_OTP_REG_9:
	case WSA881X_OTP_REG_10:
	case WSA881X_OTP_REG_11:
	case WSA881X_OTP_REG_12:
	case WSA881X_OTP_REG_13:
	case WSA881X_OTP_REG_14:
	case WSA881X_OTP_REG_15:
	case WSA881X_OTP_REG_16:
	case WSA881X_OTP_REG_17:
	case WSA881X_OTP_REG_18:
	case WSA881X_OTP_REG_19:
	case WSA881X_OTP_REG_20:
	case WSA881X_OTP_REG_21:
	case WSA881X_OTP_REG_22:
	case WSA881X_OTP_REG_23:
	case WSA881X_OTP_REG_24:
	case WSA881X_OTP_REG_25:
	case WSA881X_OTP_REG_26:
	case WSA881X_OTP_REG_27:
	case WSA881X_OTP_REG_28:
	case WSA881X_OTP_REG_29:
	case WSA881X_OTP_REG_30:
	case WSA881X_OTP_REG_31:
	case WSA881X_OTP_REG_63:
	case WSA881X_BIAS_REF_CTRL:
	case WSA881X_BIAS_TEST:
	case WSA881X_BIAS_BIAS:
	case WSA881X_TEMP_OP:
	case WSA881X_TEMP_IREF_CTRL:
	case WSA881X_TEMP_ISENS_CTRL:
	case WSA881X_TEMP_CLK_CTRL:
	case WSA881X_TEMP_TEST:
	case WSA881X_TEMP_BIAS:
	case WSA881X_TEMP_ADC_CTRL:
	case WSA881X_TEMP_DOUT_MSB:
	case WSA881X_TEMP_DOUT_LSB:
	case WSA881X_ADC_EN_MODU_V:
	case WSA881X_ADC_EN_MODU_I:
	case WSA881X_ADC_EN_DET_TEST_V:
	case WSA881X_ADC_EN_DET_TEST_I:
	case WSA881X_ADC_SEL_IBIAS:
	case WSA881X_ADC_EN_SEL_IBAIS:
	case WSA881X_SPKR_DRV_EN:
	case WSA881X_SPKR_DRV_GAIN:
	case WSA881X_SPKR_DAC_CTL:
	case WSA881X_SPKR_DRV_DBG:
	case WSA881X_SPKR_PWRSTG_DBG:
	case WSA881X_SPKR_OCP_CTL:
	case WSA881X_SPKR_CLIP_CTL:
	case WSA881X_SPKR_BBM_CTL:
	case WSA881X_SPKR_MISC_CTL1:
	case WSA881X_SPKR_MISC_CTL2:
	case WSA881X_SPKR_BIAS_INT:
	case WSA881X_SPKR_PA_INT:
	case WSA881X_SPKR_BIAS_CAL:
	case WSA881X_SPKR_BIAS_PSRR:
	case WSA881X_SPKR_STATUS1:
	case WSA881X_SPKR_STATUS2:
	case WSA881X_BOOST_EN_CTL:
	case WSA881X_BOOST_CURRENT_LIMIT:
	case WSA881X_BOOST_PS_CTL:
	case WSA881X_BOOST_PRESET_OUT1:
	case WSA881X_BOOST_PRESET_OUT2:
	case WSA881X_BOOST_FORCE_OUT:
	case WSA881X_BOOST_LDO_PROG:
	case WSA881X_BOOST_SLOPE_COMP_ISENSE_FB:
	case WSA881X_BOOST_RON_CTL:
	case WSA881X_BOOST_LOOP_STABILITY:
	case WSA881X_BOOST_ZX_CTL:
	case WSA881X_BOOST_START_CTL:
	case WSA881X_BOOST_MISC1_CTL:
	case WSA881X_BOOST_MISC2_CTL:
	case WSA881X_BOOST_MISC3_CTL:
	case WSA881X_BOOST_ATEST_CTL:
	case WSA881X_SPKR_PROT_FE_GAIN:
	case WSA881X_SPKR_PROT_FE_CM_LDO_SET:
	case WSA881X_SPKR_PROT_FE_ISENSE_BIAS_SET1:
	case WSA881X_SPKR_PROT_FE_ISENSE_BIAS_SET2:
	case WSA881X_SPKR_PROT_ATEST1:
	case WSA881X_SPKR_PROT_ATEST2:
	case WSA881X_SPKR_PROT_FE_VSENSE_VCM:
	case WSA881X_SPKR_PROT_FE_VSENSE_BIAS_SET1:
	case WSA881X_BONGO_RESRV_REG1:
	case WSA881X_BONGO_RESRV_REG2:
	case WSA881X_SPKR_PROT_SAR:
	case WSA881X_SPKR_STATUS3:
		return true;
	default:
		return false;
	}
}

static bool wsa881x_volatile_register(struct device *dev, unsigned int reg)
{
	switch (reg) {
	case WSA881X_CHIP_ID0:
	case WSA881X_CHIP_ID1:
	case WSA881X_CHIP_ID2:
	case WSA881X_CHIP_ID3:
	case WSA881X_BUS_ID:
	case WSA881X_TEMP_MSB:
	case WSA881X_TEMP_LSB:
	case WSA881X_SDM_PDM9_LSB:
	case WSA881X_SDM_PDM9_MSB:
	case WSA881X_OTP_CTRL1:
	case WSA881X_INTR_STATUS:
	case WSA881X_ATE_TEST_MODE:
	case WSA881X_PIN_STATUS:
	case WSA881X_SWR_HM_TEST2:
	case WSA881X_SPKR_STATUS1:
	case WSA881X_SPKR_STATUS2:
	case WSA881X_SPKR_STATUS3:
	case WSA881X_OTP_REG_0:
	case WSA881X_OTP_REG_1:
	case WSA881X_OTP_REG_2:
	case WSA881X_OTP_REG_3:
	case WSA881X_OTP_REG_4:
	case WSA881X_OTP_REG_5:
	case WSA881X_OTP_REG_31:
	case WSA881X_TEMP_DOUT_MSB:
	case WSA881X_TEMP_DOUT_LSB:
	case WSA881X_TEMP_OP:
	case WSA881X_SPKR_PROT_SAR:
		return true;
	default:
		return false;
	}
}

static const struct regmap_config wsa881x_regmap_config = {
	.reg_bits = 32,
	.val_bits = 8,
	.cache_type = REGCACHE_MAPLE,
	.reg_defaults = wsa881x_defaults,
	.max_register = WSA881X_SPKR_STATUS3,
	.num_reg_defaults = ARRAY_SIZE(wsa881x_defaults),
	.volatile_reg = wsa881x_volatile_register,
	.readable_reg = wsa881x_readable_register,
	.reg_format_endian = REGMAP_ENDIAN_NATIVE,
	.val_format_endian = REGMAP_ENDIAN_NATIVE,
};

enum {
	G_18DB = 0,
	G_16P5DB,
	G_15DB,
	G_13P5DB,
	G_12DB,
	G_10P5DB,
	G_9DB,
	G_7P5DB,
	G_6DB,
	G_4P5DB,
	G_3DB,
	G_1P5DB,
	G_0DB,
};

/*
 * Private data Structure for wsa881x. All parameters related to
 * WSA881X codec needs to be defined here.
 */
struct wsa881x_priv {
	struct regmap *regmap;
	struct regmap *spx_wcd_regmap;
	struct device *dev;
	struct sdw_slave *slave;
	struct sdw_stream_config sconfig;
	struct sdw_stream_runtime *sruntime;
	struct sdw_port_config port_config[WSA881X_MAX_SWR_PORTS];
	struct gpio_desc *sd_n;
	/*
	 * Logical state for SD_N GPIO: high for shutdown, low for enable.
	 * For backwards compatibility.
	 */
	unsigned int sd_n_val;
	/*
	 * SPX: wcd934x GPIO pin index driving THIS amp's SD_N, parsed from the
	 * node's own powerdown-gpios. Each amp must have its own pin: with both
	 * amps sharing one pin they power up together, collide at device 0 and
	 * the bus never enumerates.
	 */
	int spx_sd_n_pin;
	int active_ports;
	bool port_prepared[WSA881X_MAX_SWR_PORTS];
	bool port_enable[WSA881X_MAX_SWR_PORTS];
	bool spx_stream_configured;
	bool spx_write_only;
	u8 *spx_reg_shadow;
	struct mutex spx_shadow_lock;
	struct mutex spx_state_lock;
};

static int spx_powerdown_gpio = 1;
static struct gpio_desc *spx_powerdown_desc;
static struct wsa881x_priv *spx_debug_wsa881x;
static DEFINE_MUTEX(spx_debug_lock);
/*
 * DAC-only is the last configuration that produced repeatable audio on the
 * Surface hardware. Four-port transport remains an explicit experiment: it
 * produced a DOUT collision and a loud transient followed by silence.
 */
static int spx_stream_port_mask = BIT(WSA881X_PORT_DAC);
module_param(spx_stream_port_mask, int, 0644);
MODULE_PARM_DESC(spx_stream_port_mask,
		 "SPX: SoundWire sink-port mask; write-only SPX devices transport every selected port independently of analog controls");

/* Dual, assigned-device mode keeps normal addressed register writes, while
 * opting into the readless transport and proven Surface PA sequencing.
 */
static bool spx_enumerated_mode;
module_param(spx_enumerated_mode, bool, 0444);
MODULE_PARM_DESC(spx_enumerated_mode,
		 "SPX: dual assigned-device mode (write-only PortCtrl, no slave alerts, DAC-only transport, Windows PA sequence)");

static int spx_stream_device_mask = BIT(0) | BIT(1);
module_param(spx_stream_device_mask, int, 0644);
MODULE_PARM_DESC(spx_stream_device_mask,
		 "SPX: assigned devices allowed to join a stream (bit0=device1, bit1=device2)");

static bool spx_swap_dac_master_ports;
module_param(spx_swap_dac_master_ports, bool, 0644);
MODULE_PARM_DESC(spx_swap_dac_master_ports,
		 "SPX: map device1 DAC to master DP4 and device2 DAC to master DP1");

/*
 * SPX: override the DT qcom,port-mapping (slave port -> master port) at runtime.
 * The stock <1 2 3 7> is inherited from db845c and puts the speaker audio on the
 * slave's COMP port instead of its DAC port, which forces the compander
 * transport config (4 channels, long sample interval) onto the audio and leaves
 * the analog gain stuck in DRE mode. Being able to re-map without a reboot makes
 * that tunable. Zero entries keep the DT value.
 *   snd_soc_wsa881x.spx_port_map=2,1,3,7
 */
static int spx_port_map[WSA881X_MAX_SWR_PORTS];
static int spx_port_map_count;
module_param_array(spx_port_map, int, &spx_port_map_count, 0644);
MODULE_PARM_DESC(spx_port_map,
		 "SPX: master port for each slave port 1..4 (0 = keep DT value)");

/*
 * SPX: the wcd934x gpiolib chip is registered but its owner module's
 * refcount wedged negative after a codec module swap, so every
 * gpiod_request() fails with EPROBE_DEFER and wsa881x probes defer
 * forever. Drive the WSA SD_N line (wcdgpio pin 1) directly through the
 * WCD9340's SLIMbus regmap instead -- the same window the MFD driver and
 * the soundwire_qcom quiet-bus code use. VAL bit = physical level.
 *
 * Polarity, measured 2026-07-29 with spx_wsa_power_probe.ko: physical HIGH =
 * amp ON, LOW = off, matching powerdown-gpios/GPIO_ACTIVE_LOW in the DT. The
 * code below is right for a *powerdown* signal -- logical 1 = powerdown
 * asserted = physical low = amp off -- but the comment that used to sit here
 * claimed "HIGH = shutdown, logical 1 = amp active", which is inverted and is
 * the same error that made the bring-up script park the amps at 0x06 (both ON).
 */
#define SPX_WCD_GPIO_DIR_CTL	0x42
#define SPX_WCD_GPIO_VAL_CTL	0x43
#define SPX_WSA_SD_N_PIN_DFL	1

static int spx_wsa_powerdown_set(struct wsa881x_priv *wsa881x, int logical)
{
	unsigned int mask;
	u8 val;
	int ret = 0;

	if (!wsa881x || !wsa881x->spx_wcd_regmap)
		return -ENODEV;

	mask = BIT(wsa881x->spx_sd_n_pin);
	val = logical ? 0 : mask;

	ret = regmap_update_bits(wsa881x->spx_wcd_regmap,
				 SPX_WCD_GPIO_DIR_CTL, mask, mask);
	if (ret)
		return ret;
	return regmap_update_bits(wsa881x->spx_wcd_regmap,
				  SPX_WCD_GPIO_VAL_CTL, mask, val);
}

static int spx_powerdown_gpio_set(const char *val,
				  const struct kernel_param *kp)
{
	int ret = 0;

	ret = param_set_int(val, kp);
	if (ret)
		return ret;
	mutex_lock(&spx_debug_lock);
	if (spx_debug_wsa881x && spx_debug_wsa881x->spx_wcd_regmap)
		ret = spx_wsa_powerdown_set(spx_debug_wsa881x,
					    spx_powerdown_gpio);
	else if (spx_powerdown_desc)
		ret = gpiod_direction_output(spx_powerdown_desc,
					     spx_powerdown_gpio);
	mutex_unlock(&spx_debug_lock);

	return ret;
}

static const struct kernel_param_ops spx_powerdown_gpio_ops = {
	.set = spx_powerdown_gpio_set,
	.get = param_get_int,
};
module_param_cb(spx_powerdown_gpio, &spx_powerdown_gpio_ops,
		&spx_powerdown_gpio, 0644);
MODULE_PARM_DESC(spx_powerdown_gpio,
		 "SPX: logical powerdown GPIO value (applied immediately)");

/*
 * The SPX amplifiers share their SoundWire address, so reads collide while
 * broadcast writes remain usable. Build the full register value from regcache
 * and issue a direct write instead of a hardware read-modify-write.
 */
/*
 * SPX: even with native hardware enumeration (both amps at distinct device
 * numbers) the WCD9340-internal master's read FIFO underflows on this board,
 * so every read-modify-write in the DAPM power-up path fails with -EIO and the
 * bandgap/RDAC/PA sequence never completes. Writes, however, land. Compose the
 * full register value from the shadow and issue a plain write instead of ever
 * reading. Independent of spx_write_only, which also changes probe/GPIO/port
 * behaviour and stays off for the enumerated configuration.
 */
/*
 * Selects the legacy single-amp bring-up behaviour wholesale (SD_N over the WCD
 * regmap, write-only port config, spx_rearm_init). Latched per device at probe.
 */
static bool spx_write_only;
module_param(spx_write_only, bool, 0444);
MODULE_PARM_DESC(spx_write_only,
		 "SPX: legacy single-amp write-only bring-up (read at probe)");

static bool spx_blind_rmw;
module_param(spx_blind_rmw, bool, 0644);
MODULE_PARM_DESC(spx_blind_rmw,
		 "SPX: never read the amp; compose register values from the driver shadow");

static bool wsa881x_use_shadow(struct wsa881x_priv *wsa881x)
{
	return wsa881x->spx_reg_shadow &&
	       (wsa881x->spx_write_only || spx_blind_rmw ||
		spx_enumerated_mode);
}

static bool wsa881x_spx_windows_pa(struct wsa881x_priv *wsa881x)
{
	return wsa881x->spx_write_only || spx_enumerated_mode;
}

static bool wsa881x_spx_transport_enabled(struct wsa881x_priv *wsa881x)
{
	unsigned int dev_num = wsa881x->slave->dev_num;

	if (!spx_enumerated_mode)
		return true;
	return dev_num >= 1 && dev_num <= 2 &&
	       (spx_stream_device_mask & BIT(dev_num - 1));
}

static int wsa881x_update_bits(struct wsa881x_priv *wsa881x,
			       unsigned int reg, unsigned int mask,
			       unsigned int val)
{
	struct regmap *rm = wsa881x->regmap;
	u8 cached;
	int ret;

	if (!wsa881x_use_shadow(wsa881x))
		return regmap_update_bits(rm, reg, mask, val);

	if (reg > WSA881X_SPKR_STATUS3)
		return -EINVAL;

	mutex_lock(&wsa881x->spx_shadow_lock);
	cached = wsa881x->spx_reg_shadow[reg];
	cached &= ~mask;
	cached |= val & mask;
	ret = regmap_write(rm, reg, cached);
	if (!ret)
		wsa881x->spx_reg_shadow[reg] = cached;
	mutex_unlock(&wsa881x->spx_shadow_lock);

	return ret;
}

static int wsa881x_write_sequence(struct wsa881x_priv *wsa881x,
				  const struct reg_sequence *regs,
				  int num_regs)
{
	int i, ret;

	if (!wsa881x_use_shadow(wsa881x))
		return regmap_multi_reg_write(wsa881x->regmap, regs, num_regs);

	for (i = 0; i < num_regs; i++) {
		ret = wsa881x_update_bits(wsa881x, regs[i].reg, 0xff,
					  regs[i].def);
		if (ret)
			return ret;
		if (regs[i].delay_us)
			fsleep(regs[i].delay_us);
	}

	return 0;
}

static int spx_sample_edge = -1;

static int spx_sample_edge_set(const char *val, const struct kernel_param *kp)
{
	int ret = 0;

	ret = param_set_int(val, kp);
	if (ret)
		return ret;
	if (spx_sample_edge < -1 || spx_sample_edge > 0xff)
		return -EINVAL;
	mutex_lock(&spx_debug_lock);
	if (spx_debug_wsa881x && spx_sample_edge >= 0)
		ret = wsa881x_update_bits(spx_debug_wsa881x,
					   WSA881X_SAMPLE_EDGE_SEL, 0xff,
					   spx_sample_edge);
	mutex_unlock(&spx_debug_lock);

	return ret;
}

static const struct kernel_param_ops spx_sample_edge_ops = {
	.set = spx_sample_edge_set,
	.get = param_get_int,
};
module_param_cb(spx_sample_edge, &spx_sample_edge_ops, &spx_sample_edge, 0644);
MODULE_PARM_DESC(spx_sample_edge,
		 "SPX: live WSA881x PDM sample-edge register override (-1=default)");

static int spx_win_pa_seq = 1;
module_param(spx_win_pa_seq, int, 0644);
MODULE_PARM_DESC(spx_win_pa_seq,
		 "SPX: replicate the selected Windows qcauddev8180 PA bring-up");

static int spx_win_pa_profile;
module_param(spx_win_pa_profile, int, 0644);
MODULE_PARM_DESC(spx_win_pa_profile,
		 "SPX: qcauddev PA profile (0=legacy non-profile-3 path, "
		 "3=profile-3 OCP path)");

static int spx_win_bias_psrr = -1;
module_param(spx_win_bias_psrr, int, 0644);
MODULE_PARM_DESC(spx_win_bias_psrr,
		 "SPX: pre-PA SPKR_BIAS_PSRR override (-1=keep rev-2 value)");

static int spx_win_temp_op = -1;
module_param(spx_win_temp_op, int, 0644);
MODULE_PARM_DESC(spx_win_temp_op,
		 "SPX: cold TEMP_OP override (-1=keep rev-2 value, 0x0c=Windows profile-3 value)");

static int spx_win_boost_loop_stab = -1;
module_param(spx_win_boost_loop_stab, int, 0644);
MODULE_PARM_DESC(spx_win_boost_loop_stab,
		 "SPX: cold BOOST_LOOP_STABILITY override (-1=composed rev-2 value; Windows writes 0x8f)");

static int spx_win_misc_ctl1 = -1;
module_param(spx_win_misc_ctl1, int, 0644);
MODULE_PARM_DESC(spx_win_misc_ctl1,
		 "SPX: SPKR_MISC_CTL1 override (-1=legacy 0x87 stream value; Windows composes 0xc6 in cold init, 0xc7 at PA time when the gain code is >= 4)");

/*
 * SPX: default OFF. Replaying the ~100-register init table inside PRE_PMU costs
 * ~240 ms of bus traffic on every stream start, while the port is already
 * streaming -- measured 2026-07-27 as "mostly silent + static" with it on vs
 * "tone + static" with it off. Windows never re-inits per stream. The recovery
 * script still replays explicitly via spx_rearm_init after a power-cycle, which
 * is the only case that actually needs it.
 */
static int spx_init_on_pmu;
module_param(spx_init_on_pmu, int, 0644);
MODULE_PARM_DESC(spx_init_on_pmu,
		 "SPX: replay the amp init table before every PA enable");

/*
 * A Surface amp can lose its hardware register state while ASoC still has the
 * DAPM supplies marked on. Replaying the complete cold-init table here was
 * measured to make playback worse (~240 ms of traffic), but the four supply
 * writes are small, idempotent, and required before the PA is enabled.
 */
static bool spx_replay_supplies = true;
module_param(spx_replay_supplies, bool, 0644);
MODULE_PARM_DESC(spx_replay_supplies,
		 "SPX: replay DCLK, ACLK, bandgap and RDAC state before every PA enable");

static int spx_win_gain_singleshot;
module_param(spx_win_gain_singleshot, int, 0644);
MODULE_PARM_DESC(spx_win_gain_singleshot,
		 "SPX: write SPKR_DRV_GAIN once without the 1 ms/step ramp when the target gain code is >= 4, like Windows (0=legacy ramp)");

/*
 * SPX: Windows soft-resets the WSA digital core between streams
 * (SWR_RESET_EN=0x07 then CDC_RST_CTL=0x00) and relies on its open path
 * re-running the full cold-init table on the next stream. Linux only replays
 * init on request, so arming this WITHOUT a matching cold-init replay
 * (spx_init_on_pmu=1, or an spx_wsa_seq/spx_rearm_init call per stream)
 * leaves the amp dead after the first teardown.
 */
static int spx_win_teardown_reset;
module_param(spx_win_teardown_reset, int, 0644);
MODULE_PARM_DESC(spx_win_teardown_reset,
		 "SPX: reset the amp digital core at teardown (0x300b=0x07 then 0x3005=0x00); the NEXT stream must re-run the full cold-init table (pair with spx_init_on_pmu=1)");

static int wsa881x_init(struct wsa881x_priv *wsa881x)
{
	struct regmap *rm = wsa881x->regmap;
	unsigned int val = 0;
	int i, ret = 0;

#define WSA881X_INIT_WRITE(_reg, _mask, _val) do { \
	if (!ret) \
		ret = wsa881x_update_bits(wsa881x, (_reg), (_mask), (_val)); \
} while (0)

	if ((spx_win_misc_ctl1 != -1 &&
	     (spx_win_misc_ctl1 < 0 || spx_win_misc_ctl1 > 0xff)) ||
	    (spx_win_boost_loop_stab != -1 &&
	     (spx_win_boost_loop_stab < 0 || spx_win_boost_loop_stab > 0xff)))
		return -EINVAL;

	if (wsa881x_spx_windows_pa(wsa881x))
		dev_info(wsa881x->dev,
			 "SPX: initializing amplifier at SoundWire device %d\n",
			 wsa881x->slave->dev_num);

	if (wsa881x_spx_windows_pa(wsa881x)) {
		if (spx_win_bias_psrr != -1 && spx_win_bias_psrr != 0x45)
			return -EINVAL;
		if (spx_win_temp_op != -1 && spx_win_temp_op != 0x0c)
			return -EINVAL;
		/* TEMP_OP is a regcache default, not a rev-2 patch entry. */
		if (spx_win_temp_op == 0x0c) {
			dev_info(wsa881x->dev,
				 "SPX: Windows TEMP_OP override 0x%02x\n",
				 spx_win_temp_op);
			WSA881X_INIT_WRITE(WSA881X_TEMP_OP, 0xff,
					    spx_win_temp_op);
		}
		for (i = 0; i < ARRAY_SIZE(wsa881x_rev_2_0); i++) {
			unsigned int def = wsa881x_rev_2_0[i].def;

			if (wsa881x_rev_2_0[i].reg == WSA881X_SPKR_BIAS_PSRR &&
			    spx_win_bias_psrr == 0x45) {
				def = spx_win_bias_psrr;
				dev_info(wsa881x->dev,
					 "SPX: Windows BIAS_PSRR override 0x%02x\n",
					 def);
			}
			WSA881X_INIT_WRITE(wsa881x_rev_2_0[i].reg, 0xff,
					    def);
			if (ret)
				break;
		}
	} else {
		ret = regmap_register_patch(wsa881x->regmap, wsa881x_rev_2_0,
					    ARRAY_SIZE(wsa881x_rev_2_0));
	}

	/* Enable software reset output from soundwire slave */
	WSA881X_INIT_WRITE(WSA881X_SWR_RESET_EN, 0x07, 0x07);

	/*
	 * The live 2023 Windows driver performs the reset and clock transition
	 * as full writes in this order (qcauddev8180!0x1400979b0).  In
	 * particular, CDC_RST_CTL must pass through 0x02 before reaching 0x03;
	 * two update_bits() calls are not equivalent on the write-only SPX bus.
	 */
	if (wsa881x_spx_windows_pa(wsa881x)) {
		WSA881X_INIT_WRITE(WSA881X_CDC_RST_CTL, 0xff, 0x02);
		WSA881X_INIT_WRITE(WSA881X_CDC_RST_CTL, 0xff, 0x03);
		WSA881X_INIT_WRITE(WSA881X_CDC_DIG_CLK_CTL, 0xff, 0x01);
		WSA881X_INIT_WRITE(WSA881X_CDC_ANA_CLK_CTL, 0xff, 0x01);
		WSA881X_INIT_WRITE(WSA881X_SPKR_OCP_CTL, 0xff, 0xd6);
	} else {
		/* Bring out of analog reset */
		WSA881X_INIT_WRITE(WSA881X_CDC_RST_CTL, 0x02, 0x02);

		/* Bring out of digital reset */
		WSA881X_INIT_WRITE(WSA881X_CDC_RST_CTL, 0x01, 0x01);
	}
	WSA881X_INIT_WRITE(WSA881X_CLOCK_CONFIG, 0x10, 0x10);
	WSA881X_INIT_WRITE(WSA881X_SPKR_OCP_CTL, 0x02, 0x02);
	WSA881X_INIT_WRITE(WSA881X_SPKR_MISC_CTL1, 0xC0, 0x80);
	WSA881X_INIT_WRITE(WSA881X_SPKR_MISC_CTL1, 0x06, 0x06);
	if (spx_win_misc_ctl1 >= 0) {
		dev_info(wsa881x->dev,
			 "SPX: Windows SPKR_MISC_CTL1 init override 0x%02x\n",
			 spx_win_misc_ctl1);
		/* Full-width: the intended FINAL byte, not a compose. */
		WSA881X_INIT_WRITE(WSA881X_SPKR_MISC_CTL1, 0xff,
				   spx_win_misc_ctl1);
	}
	WSA881X_INIT_WRITE(WSA881X_SPKR_BIAS_INT, 0xFF, 0x00);
	WSA881X_INIT_WRITE(WSA881X_SPKR_PA_INT, 0xF0, 0x40);
	WSA881X_INIT_WRITE(WSA881X_SPKR_PA_INT, 0x0E, 0x0E);
	WSA881X_INIT_WRITE(WSA881X_BOOST_LOOP_STABILITY, 0x03, 0x03);
	WSA881X_INIT_WRITE(WSA881X_BOOST_MISC2_CTL, 0xFF, 0x14);
	WSA881X_INIT_WRITE(WSA881X_BOOST_START_CTL, 0x80, 0x80);
	WSA881X_INIT_WRITE(WSA881X_BOOST_START_CTL, 0x03, 0x00);
	WSA881X_INIT_WRITE(WSA881X_BOOST_SLOPE_COMP_ISENSE_FB, 0x0C, 0x04);
	WSA881X_INIT_WRITE(WSA881X_BOOST_SLOPE_COMP_ISENSE_FB, 0x03, 0x00);

	if (wsa881x_use_shadow(wsa881x))
		val = wsa881x->spx_reg_shadow[WSA881X_OTP_REG_0];
	else if (regmap_read(rm, WSA881X_OTP_REG_0, &val))
		val = 0;
	if (val)
		WSA881X_INIT_WRITE(WSA881X_BOOST_PRESET_OUT1, 0xF0, 0x70);

	WSA881X_INIT_WRITE(WSA881X_BOOST_PRESET_OUT2, 0xF0, 0x30);
	if (spx_win_boost_loop_stab >= 0) {
		dev_info(wsa881x->dev,
			 "SPX: Windows BOOST_LOOP_STABILITY override 0x%02x\n",
			 spx_win_boost_loop_stab);
		/* Full-width: the intended FINAL byte, not a compose. */
		WSA881X_INIT_WRITE(WSA881X_BOOST_LOOP_STABILITY, 0xff,
				   spx_win_boost_loop_stab);
	}
	WSA881X_INIT_WRITE(WSA881X_SPKR_DRV_EN, 0x08, 0x08);
	WSA881X_INIT_WRITE(WSA881X_BOOST_CURRENT_LIMIT, 0x0F, 0x08);
	WSA881X_INIT_WRITE(WSA881X_SPKR_OCP_CTL, 0x30, 0x30);
	WSA881X_INIT_WRITE(WSA881X_SPKR_OCP_CTL, 0x0C, 0x00);
	WSA881X_INIT_WRITE(WSA881X_OTP_REG_28, 0x3F, 0x3A);
	WSA881X_INIT_WRITE(WSA881X_BONGO_RESRV_REG1, 0xFF, 0xB2);
	WSA881X_INIT_WRITE(WSA881X_BONGO_RESRV_REG2, 0xFF, 0x05);

	/*
	 * SPX runs the guarded baseline without the VISENSE port or Qualcomm's
	 * device-0x45 protection algorithm/calibration. The sequence previously
	 * placed here (0x313a=66->67->47, 0x3115=11, 0x3110/0x3111=80) is not
	 * generic Windows cold init: qcauddev8180!0x14009adc8 executes it only
	 * when speaker protection is enabled. Leaving the current modulator at
	 * 0x3111=0x80 on our uncalibrated DAC-only path is a concrete Windows/Linux
	 * state mismatch and a plausible source of analog noise.
	 *
	 * Replay DriverStore qcauddev8180.sys at 0x14008e794 (SHA-256
	 * 47a1b7b7167141fe...) exactly. If Linux later implements
	 * the protection TX stream plus module 0x1025f calibration, that mode
	 * needs an explicit opt-in rather than another unconditional cold write.
	 */
	if (wsa881x_spx_windows_pa(wsa881x)) {
		WSA881X_INIT_WRITE(WSA881X_ADC_EN_MODU_V, 0xff, 0x00);
		WSA881X_INIT_WRITE(WSA881X_ADC_EN_MODU_I, 0xff, 0x00);
		WSA881X_INIT_WRITE(WSA881X_SPKR_PROT_FE_VSENSE_VCM, 0xff, 0x95);
		fsleep(1000);
		WSA881X_INIT_WRITE(WSA881X_SPKR_PROT_FE_GAIN, 0xff, 0xce);
	}

#undef WSA881X_INIT_WRITE
	return ret;
}

/*
 * SPX live re-arm: the boot-time wsa881x_init() and the DAPM PRE_PMU
 * sequences can fire while the physical amp is still off. Writing this
 * parameter while the stream is idle replays only the complete cold-start
 * table. DAPM will enable supplies, boost and PA later, after SoundWire ports
 * have been prepared; enabling them here would violate the ports-before-PA
 * ordering and can produce a transient or silence.
 */
static int spx_rearm_init_set(const char *val, const struct kernel_param *kp)
{
	struct wsa881x_priv *wsa881x;
	int i, ret = 0;

	mutex_lock(&spx_debug_lock);
	wsa881x = spx_debug_wsa881x;
	if (!wsa881x || !wsa881x->spx_write_only)
		ret = -ENODEV;
	if (ret)
		goto out;

	mutex_lock(&wsa881x->spx_state_lock);
	if (READ_ONCE(wsa881x->spx_stream_configured)) {
		ret = -EBUSY;
		goto state_out;
	}
	for (i = 0; i < WSA881X_MAX_SWR_PORTS; i++) {
		if (wsa881x->port_prepared[i]) {
			ret = -EBUSY;
			goto state_out;
		}
	}

	dev_info(wsa881x->dev,
		 "SPX: replaying cold amplifier init while stream is idle\n");

	/* Full cold-start register programming. */
	ret = wsa881x_init(wsa881x);
	if (!ret)
		dev_info(wsa881x->dev, "SPX: cold init replay complete\n");
state_out:
	mutex_unlock(&wsa881x->spx_state_lock);
out:
	mutex_unlock(&spx_debug_lock);
	return ret;
}

static const struct kernel_param_ops spx_rearm_init_ops = {
	.set = spx_rearm_init_set,
};
module_param_cb(spx_rearm_init, &spx_rearm_init_ops, NULL, 0200);
MODULE_PARM_DESC(spx_rearm_init,
		 "SPX: write to replay cold amp init while the stream is idle");

static int wsa881x_component_probe(struct snd_soc_component *comp)
{
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);
	static const struct snd_soc_dapm_route spx_stream_route = {
		"RDAC", NULL, "SPKR Playback"
	};
	int ret;

	snd_soc_component_init_regmap(comp, wsa881x->regmap);
	if (wsa881x->spx_write_only) {
		ret = snd_soc_dapm_add_routes(&comp->dapm, &spx_stream_route, 1);
		if (ret)
			return ret;
		dev_info(comp->dev,
			 "SPX: connected SPKR Playback directly to RDAC\n");
	}

	return 0;
}

static int wsa881x_get_pa_gain(struct snd_kcontrol *kc,
				       struct snd_ctl_elem_value *ucontrol)
{
	struct snd_soc_component *comp = snd_soc_kcontrol_component(kc);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);
	struct soc_mixer_control *mc =
		(struct soc_mixer_control *)kc->private_value;
	unsigned int mask = (1 << fls(mc->max)) - 1;
	unsigned int val;

	if (!wsa881x_use_shadow(wsa881x))
		return snd_soc_get_volsw(kc, ucontrol);
	if (mc->reg > WSA881X_SPKR_STATUS3)
		return -EINVAL;

	mutex_lock(&wsa881x->spx_shadow_lock);
	val = (wsa881x->spx_reg_shadow[mc->reg] >> mc->shift) & mask;
	mutex_unlock(&wsa881x->spx_shadow_lock);
	if (mc->invert)
		val = mc->max - val;
	ucontrol->value.integer.value[0] = val;
	return 0;
}

static int wsa881x_put_pa_gain(struct snd_kcontrol *kc,
			       struct snd_ctl_elem_value *ucontrol)
{
	struct snd_soc_component *comp = snd_soc_kcontrol_component(kc);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);
	struct soc_mixer_control *mc =
			(struct soc_mixer_control *)kc->private_value;
	int max = mc->max;
	unsigned int mask = (1 << fls(max)) - 1;
	int val, ret, min_gain, max_gain;

	ret = pm_runtime_resume_and_get(comp->dev);
	if (ret < 0 && ret != -EACCES)
		return ret;

	max_gain = (max - ucontrol->value.integer.value[0]) & mask;
	/*
	 * Gain has to set incrementally in 4 steps
	 * as per HW sequence
	 */
	if (max_gain > G_4P5DB)
		min_gain = G_0DB;
	else
		min_gain = max_gain + 3;
	/*
	 * 1ms delay is needed before change in gain
	 * as per HW requirement.
	 */
	usleep_range(1000, 1010);

	for (val = min_gain; max_gain <= val; val--) {
		ret = wsa881x_update_bits(wsa881x, WSA881X_SPKR_DRV_GAIN,
					    WSA881X_SPKR_PAG_GAIN_MASK,
					    val << 4);
		if (ret < 0)
			dev_err(comp->dev, "Failed to change PA gain");

		usleep_range(1000, 1010);
	}

	pm_runtime_put_autosuspend(comp->dev);

	return 1;
}

static int wsa881x_get_port(struct snd_kcontrol *kcontrol,
			    struct snd_ctl_elem_value *ucontrol)
{
	struct snd_soc_component *comp = snd_soc_kcontrol_component(kcontrol);
	struct wsa881x_priv *data = snd_soc_component_get_drvdata(comp);
	struct soc_mixer_control *mixer =
		(struct soc_mixer_control *)kcontrol->private_value;
	int portidx = mixer->reg;

	ucontrol->value.integer.value[0] = data->port_enable[portidx];


	return 0;
}

static int wsa881x_boost_ctrl(struct snd_soc_component *comp, bool enable)
{
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	if (enable)
		wsa881x_update_bits(wsa881x, WSA881X_BOOST_EN_CTL,
				     WSA881X_BOOST_EN_MASK, WSA881X_BOOST_EN);
	else
		wsa881x_update_bits(wsa881x, WSA881X_BOOST_EN_CTL,
				     WSA881X_BOOST_EN_MASK, 0);
	/*
	 * 1.5ms sleep is needed after boost enable/disable as per
	 * HW requirement
	 */
	usleep_range(1500, 1510);
	return 0;
}

static int wsa881x_set_port(struct snd_kcontrol *kcontrol,
			    struct snd_ctl_elem_value *ucontrol)
{
	struct snd_soc_component *comp = snd_soc_kcontrol_component(kcontrol);
	struct wsa881x_priv *data = snd_soc_component_get_drvdata(comp);
	struct soc_mixer_control *mixer =
		(struct soc_mixer_control *)kcontrol->private_value;
	int portidx = mixer->reg;

	if (ucontrol->value.integer.value[0]) {
		if (data->port_enable[portidx])
			return 0;

		data->port_enable[portidx] = true;
	} else {
		if (!data->port_enable[portidx])
			return 0;

		data->port_enable[portidx] = false;
	}

	/*
	 * SPX: do NOT let the COMP switch rewrite PA_GAIN_SEL (upstream's
	 * set_port only handles BOOST). Coupling the two meant toggling the
	 * compander also flipped the analog gain source, so the only way to get
	 * register-controlled gain was to drop the COMP data port entirely.
	 */
	if (portidx == WSA881X_PORT_BOOST) /* Boost Switch */
		wsa881x_boost_ctrl(comp, data->port_enable[portidx]);

	return 1;
}

static const char * const smart_boost_lvl_text[] = {
	"6.625 V", "6.750 V", "6.875 V", "7.000 V",
	"7.125 V", "7.250 V", "7.375 V", "7.500 V",
	"7.625 V", "7.750 V", "7.875 V", "8.000 V",
	"8.125 V", "8.250 V", "8.375 V", "8.500 V"
};

static const struct soc_enum smart_boost_lvl_enum =
	SOC_ENUM_SINGLE(WSA881X_BOOST_PRESET_OUT1, 0,
			ARRAY_SIZE(smart_boost_lvl_text),
			smart_boost_lvl_text);

static const DECLARE_TLV_DB_SCALE(pa_gain, 0, 150, 0);

static const struct snd_kcontrol_new wsa881x_snd_controls[] = {
	SOC_ENUM("Smart Boost Level", smart_boost_lvl_enum),
	WSA881X_PA_GAIN_TLV("PA Volume", WSA881X_SPKR_DRV_GAIN,
			    4, 0xC, 1, pa_gain),
	SOC_SINGLE_EXT("DAC Switch", WSA881X_PORT_DAC, 0, 1, 0,
		       wsa881x_get_port, wsa881x_set_port),
	SOC_SINGLE_EXT("COMP Switch", WSA881X_PORT_COMP, 0, 1, 0,
		       wsa881x_get_port, wsa881x_set_port),
	SOC_SINGLE_EXT("BOOST Switch", WSA881X_PORT_BOOST, 0, 1, 0,
		       wsa881x_get_port, wsa881x_set_port),
	SOC_SINGLE_EXT("VISENSE Switch", WSA881X_PORT_VISENSE, 0, 1, 0,
		       wsa881x_get_port, wsa881x_set_port),
};

static const struct snd_soc_dapm_route wsa881x_audio_map[] = {
	{ "RDAC", NULL, "IN" },
	{ "RDAC", NULL, "DCLK" },
	{ "RDAC", NULL, "ACLK" },
	{ "RDAC", NULL, "Bandgap" },
	{ "SPKR PGA", NULL, "RDAC" },
	{ "SPKR", NULL, "SPKR PGA" },
};

static int wsa881x_visense_txfe_ctrl(struct snd_soc_component *comp,
				     bool enable)
{
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	if (enable) {
		wsa881x_write_sequence(wsa881x, wsa881x_vi_txfe_en_2_0,
					ARRAY_SIZE(wsa881x_vi_txfe_en_2_0));
	} else {
		wsa881x_update_bits(wsa881x, WSA881X_SPKR_PROT_FE_VSENSE_VCM,
				     0x08, 0x08);
		/*
		 * 200us sleep is needed after visense txfe disable as per
		 * HW requirement.
		 */
		usleep_range(200, 210);
		wsa881x_update_bits(wsa881x, WSA881X_SPKR_PROT_FE_GAIN,
				     0x01, 0x00);
	}
	return 0;
}

static int wsa881x_visense_adc_ctrl(struct snd_soc_component *comp,
				    bool enable)
{
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	wsa881x_update_bits(wsa881x, WSA881X_ADC_EN_MODU_V, BIT(7),
			     enable << 7);
	wsa881x_update_bits(wsa881x, WSA881X_ADC_EN_MODU_I, BIT(7),
			     enable << 7);
	return 0;
}

static int wsa881x_spkr_pa_event(struct snd_soc_dapm_widget *w,
				 struct snd_kcontrol *kcontrol, int event)
{
	struct snd_soc_component *comp = snd_soc_dapm_to_component(w->dapm);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);
	bool transport_enabled = wsa881x_spx_transport_enabled(wsa881x);
	bool spx_pa = wsa881x_spx_windows_pa(wsa881x);
	u8 pa_gain = 0;
	int ret = 0;

#define WSA881X_PA_WRITE(_reg, _mask, _val) do { \
	if (!ret) \
		ret = wsa881x_update_bits(wsa881x, (_reg), (_mask), (_val)); \
} while (0)

	if (!transport_enabled) {
		if (event == SND_SOC_DAPM_PRE_PMU ||
		    event == SND_SOC_DAPM_POST_PMD)
			return wsa881x_update_bits(wsa881x,
				WSA881X_SPKR_DRV_EN, 0x80, 0x00);
		return 0;
	}

	if (spx_pa)
		dev_info(comp->dev, "SPX: PA DAPM event 0x%x device=%u\n",
			 event, wsa881x->slave->dev_num);

	switch (event) {
	case SND_SOC_DAPM_PRE_PMU:
		/*
		 * SPX: capture the user's PA volume BEFORE the init replay --
		 * the init table reseeds SPKR_DRV_GAIN to the 0 dB floor, and
		 * the gain write below puts the captured value back.
		 */
		if (spx_pa)
			pa_gain = wsa881x->spx_reg_shadow[WSA881X_SPKR_DRV_GAIN] &
				  WSA881X_SPKR_PAG_GAIN_MASK;
		/*
		 * SPX: the amp loses all register state whenever it drops off
		 * the bus and gets power-cycled back (which the soundwire-qcom
		 * watchdog does automatically). Replay the whole init table
		 * before every PA enable so playback never runs on a
		 * factory-reset amp; the writes are idempotent when the state
		 * was already good.
		 */
		if (wsa881x->spx_write_only && spx_init_on_pmu) {
			ret = wsa881x_init(wsa881x);
			if (ret)
				return ret;
		}

		/*
		 * DAPM's software state survives a SoundWire de/re-enumeration or
		 * SD_N recovery, while these hardware bits do not. Restore only
		 * the essential supplies here; unlike wsa881x_init(), this is four
		 * idempotent writes and does not delay an already-running stream.
		 */
		if (wsa881x->spx_write_only && spx_replay_supplies) {
			ret = wsa881x_update_bits(wsa881x,
						  WSA881X_CDC_DIG_CLK_CTL,
						  BIT(0), BIT(0));
			if (ret)
				return ret;
			ret = wsa881x_update_bits(wsa881x,
						  WSA881X_CDC_ANA_CLK_CTL,
						  BIT(0), BIT(0));
			if (ret)
				return ret;
			ret = wsa881x_update_bits(wsa881x, WSA881X_TEMP_OP,
						  BIT(3), BIT(3));
			if (ret)
				return ret;
			ret = wsa881x_update_bits(wsa881x,
						  WSA881X_SPKR_DAC_CTL,
						  BIT(7), BIT(7));
			if (ret)
				return ret;
		}

		/*
		 * SPX: enable the boost converter here, not only when the
		 * BOOST mixer control changes. wsa881x_boost_ctrl() is reached
		 * exclusively from wsa881x_set_port(), which early-returns when
		 * the control's value is unchanged -- so port_enable[BOOST]
		 * stays true across a re-enumeration while the amp, which loses
		 * every register when it power-cycles, comes back with
		 * BOOST_EN_CTL cleared. Re-setting the switch is then an ALSA
		 * no-op and 0x312a is never written again: the PA is commanded
		 * on with no boosted supply behind it. Verified on SPX --
		 * 0x312a appeared in zero write traces across a whole session.
		 * The write is idempotent when the boost is already up.
		 */
		if (wsa881x->port_enable[WSA881X_PORT_BOOST]) {
			WSA881X_PA_WRITE(WSA881X_BOOST_EN_CTL,
					  WSA881X_BOOST_EN_MASK,
					  WSA881X_BOOST_EN);
			/* 1.5 ms settle after boost enable, per HW spec. */
			usleep_range(1500, 1510);
		}

		WSA881X_PA_WRITE(WSA881X_SPKR_OCP_CTL,
				  WSA881X_SPKR_OCP_MASK,
				  WSA881X_SPKR_OCP_EN);
		if (!ret) {
			struct reg_sequence
				pre_pmu_pa[ARRAY_SIZE(wsa881x_pre_pmu_pa_2_0)];
			int idx;

			for (idx = 0; idx < ARRAY_SIZE(pre_pmu_pa); idx++)
				pre_pmu_pa[idx] = wsa881x_pre_pmu_pa_2_0[idx];

			/*
			 * SPX: Windows composes SPKR_MISC_CTL1 0xc6 during
			 * cold init and raises bit0 to 0xc7 at PA time for
			 * gain codes >= 4 (qcauddev8180 0x140097ce8/d6c,
			 * RMW 0x1400982ac-344). Substitute that final value
			 * for the hard-coded 0x87 when the knob is armed.
			 */
			if (spx_win_misc_ctl1 >= 0 &&
			    pre_pmu_pa[1].reg == WSA881X_SPKR_MISC_CTL1) {
				dev_info(comp->dev,
					 "SPX: Windows SPKR_MISC_CTL1 stream value 0x%02x\n",
					 spx_win_misc_ctl1);
				pre_pmu_pa[1].def = spx_win_misc_ctl1;
			}

			ret = wsa881x_write_sequence(wsa881x, pre_pmu_pa,
						     ARRAY_SIZE(pre_pmu_pa));
		}

		/*
		 * SPX: always take the analog gain from the REGISTER, as
		 * upstream does. Selecting DRE whenever the COMP port happened
		 * to be enabled slaved the PA gain to the compander/DRE stream
		 * and left it parked at its floor (~18 dB down), which also
		 * made "SpkrLeft PA Volume" a no-op: in DRE mode the
		 * SPKR_PAG_GAIN[7:4] field this control writes is ignored.
		 */
		WSA881X_PA_WRITE(WSA881X_SPKR_DRV_GAIN,
				  WSA881X_PA_GAIN_SEL_MASK |
				  (spx_pa ?
				   WSA881X_SPKR_PAG_GAIN_MASK : 0),
				  WSA881X_PA_GAIN_SEL_REG | pa_gain);

		/*
		 * SPX: replicate the selected analog bring-up that the Windows
		 * driver performs and mainline does not. DriverStore
		 * qcauddev8180.sys (SHA-256 47a1b7b7167141fe...) implements this
		 * at 0x140099058, with the profile branch at 0x140099248:
		 *
		 *  - The surrounding decoded path's ANA_CTL bit2 pulse is an
		 *    analog-path latch. Without it the
		 *    chain stays half-configured, which is what our
		 *    gain-proportional ("multiplicative") static looks like.
		 *  - Profile 3 writes SPKR_DAC_CTL=0xc2 directly, then pulses the
		 *    OCP control 0xb4 -> 0xb6 -> 0xb2. The mutually exclusive
		 *    non-profile-3 path instead stages DAC 0x62 -> 0x42 and runs
		 *    a VI diagnostic pulse; combining those branches is invalid.
		 *  - Retain Linux's existing one-code-per-ms gain walk as an
		 *    approximation of qcauddev's common thresholded gain ramp.
		 *
		 * Linux lacks the calibrated protection TX path used by the complete
		 * Windows profile-3 configuration, so this opt-in changes only the PA
		 * branch and deliberately leaves VISENSE/protection disabled.
		 */
		if (spx_pa && spx_win_pa_seq) {
			int step;

			dev_info(comp->dev, "SPX: Windows PA profile %d\n",
				 spx_win_pa_profile);

			WSA881X_PA_WRITE(WSA881X_ANA_CTL, BIT(2), BIT(2));
			fsleep(1000);
			WSA881X_PA_WRITE(WSA881X_ANA_CTL, BIT(2), 0);

			if (spx_win_pa_profile != 3) {
				WSA881X_PA_WRITE(WSA881X_SPKR_DAC_CTL, 0xff,
						  0x62);
				WSA881X_PA_WRITE(WSA881X_SPKR_DAC_CTL, 0xff,
						  0x42);
			}
			WSA881X_PA_WRITE(WSA881X_SPKR_DAC_CTL, 0xff, 0xc2);
			WSA881X_PA_WRITE(WSA881X_SPKR_OCP_CTL, 0xff, 0xb4);

			if (spx_win_pa_profile == 3) {
				WSA881X_PA_WRITE(WSA881X_SPKR_OCP_CTL, 0xff,
						  0xb6);
				WSA881X_PA_WRITE(WSA881X_SPKR_OCP_CTL, 0xff,
						  0xb2);
				WSA881X_PA_WRITE(WSA881X_SPKR_DRV_EN, 0xff,
						  0xfc);
				fsleep(2000);
			} else {
				WSA881X_PA_WRITE(WSA881X_ADC_EN_DET_TEST_I, 0xff,
						  0x01);
				WSA881X_PA_WRITE(WSA881X_ADC_EN_MODU_V, 0xff,
						  0x02);
				WSA881X_PA_WRITE(WSA881X_ADC_EN_DET_TEST_V, 0xff,
						  0x10);
				WSA881X_PA_WRITE(WSA881X_SPKR_PWRSTG_DBG, 0xff,
						  0xa0);
				WSA881X_PA_WRITE(WSA881X_SPKR_DRV_EN, 0xff,
						  0xfc);
				fsleep(2000);

				WSA881X_PA_WRITE(WSA881X_SPKR_PWRSTG_DBG, 0xff,
						  0x00);
				WSA881X_PA_WRITE(WSA881X_ADC_EN_DET_TEST_V, 0xff,
						  0x00);
				WSA881X_PA_WRITE(WSA881X_ADC_EN_MODU_V, 0xff,
						  0x00);
				WSA881X_PA_WRITE(WSA881X_ADC_EN_DET_TEST_I, 0xff,
						  0x00);
				fsleep(1000);
			}

			/*
			 * SPX: Windows writes SPKR_DRV_GAIN ONCE when the
			 * target gain code is >= 4 (compute T=max(requested,4)
			 * at 0x140098254-94); the 0x30/0x20/0x10 descent fires
			 * only for requested codes <= 3 (ramp gate
			 * 0x140098494-548). The unconditional final write below
			 * stays in both modes.
			 */
			if (!spx_win_gain_singleshot || (pa_gain >> 4) < 4) {
				/* Ramp PAG_GAIN down from the 0 dB floor
				 * (code 0xc) to the requested code, 1 ms
				 * per step.
				 */
				for (step = 0xc; step > (pa_gain >> 4); step--) {
					WSA881X_PA_WRITE(WSA881X_SPKR_DRV_GAIN,
							  WSA881X_SPKR_PAG_GAIN_MASK,
							  step << 4);
					fsleep(1000);
				}
			}
			WSA881X_PA_WRITE(WSA881X_SPKR_DRV_GAIN,
					  WSA881X_SPKR_PAG_GAIN_MASK, pa_gain);
			/*
			 * qcauddev gates this final pair on an opaque codec-subtype
			 * field. Preserve the established SPX subtype behavior.
			 */
			WSA881X_PA_WRITE(WSA881X_SPKR_DRV_EN, 0xff, 0xfd);
			WSA881X_PA_WRITE(WSA881X_SPKR_BIAS_CAL, 0xff, 0xac);
		}
		if (ret)
			goto pa_fail;
		break;
	case SND_SOC_DAPM_POST_PMU:
		if (wsa881x->port_prepared[WSA881X_PORT_VISENSE]) {
			wsa881x_visense_txfe_ctrl(comp, true);
			wsa881x_update_bits(wsa881x, WSA881X_ADC_EN_SEL_IBAIS,
					     0x07, 0x01);
			wsa881x_visense_adc_ctrl(comp, true);
		}

		break;
	case SND_SOC_DAPM_POST_PMD:
		if (wsa881x->port_prepared[WSA881X_PORT_VISENSE]) {
			wsa881x_visense_adc_ctrl(comp, false);
			wsa881x_visense_txfe_ctrl(comp, false);
		}

		wsa881x_update_bits(wsa881x, WSA881X_SPKR_OCP_CTL,
				     WSA881X_SPKR_OCP_MASK,
				     WSA881X_SPKR_OCP_EN |
				     WSA881X_SPKR_OCP_HOLD);
		if (spx_win_teardown_reset) {
			/*
			 * SPX: Windows parks the amp with a digital-core reset
			 * between streams (PA-off fn 0x14009933c:
			 * 0x300b=0x07 then 0x3005=0x00, in this exact order).
			 * Kept last, no sleeps: DAPM is tearing the supplies
			 * down. The next stream must re-run the full cold-init
			 * table (see the spx_win_teardown_reset PARM_DESC).
			 */
			wsa881x_update_bits(wsa881x, WSA881X_SWR_RESET_EN,
					     0xff, 0x07);
			wsa881x_update_bits(wsa881x, WSA881X_CDC_RST_CTL,
					     0xff, 0x00);
		}
		break;
	}
#undef WSA881X_PA_WRITE
	return 0;

pa_fail:
	/* Best effort: do not leave the output driver enabled after a partial
	 * software-visible PA sequence failure. Preserve the original error.
	 */
	wsa881x_update_bits(wsa881x, WSA881X_SPKR_DRV_EN, 0x80, 0x00);
	return ret;
}

static int wsa881x_rdac_event(struct snd_soc_dapm_widget *w,
			      struct snd_kcontrol *kcontrol, int event)
{
	struct snd_soc_component *comp = snd_soc_dapm_to_component(w->dapm);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	if (!wsa881x_spx_transport_enabled(wsa881x))
		return wsa881x_update_bits(wsa881x, WSA881X_SPKR_DAC_CTL,
					   BIT(7), 0);

	if (wsa881x_spx_windows_pa(wsa881x))
		dev_info(comp->dev, "SPX: RDAC DAPM event 0x%x device=%u\n",
			 event, wsa881x->slave->dev_num);

	return wsa881x_update_bits(wsa881x, WSA881X_SPKR_DAC_CTL, BIT(7),
				     event == SND_SOC_DAPM_PRE_PMU ? BIT(7) : 0);
}

static int wsa881x_bandgap_event(struct snd_soc_dapm_widget *w,
				 struct snd_kcontrol *kcontrol, int event)
{
	struct snd_soc_component *comp = snd_soc_dapm_to_component(w->dapm);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	return wsa881x_update_bits(wsa881x, WSA881X_TEMP_OP, BIT(3),
				     event == SND_SOC_DAPM_PRE_PMU ? BIT(3) : 0);
}

static int wsa881x_dclk_event(struct snd_soc_dapm_widget *w,
			      struct snd_kcontrol *kcontrol, int event)
{
	struct snd_soc_component *comp = snd_soc_dapm_to_component(w->dapm);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	return wsa881x_update_bits(wsa881x, WSA881X_CDC_DIG_CLK_CTL, BIT(0),
				     event == SND_SOC_DAPM_PRE_PMU ? BIT(0) : 0);
}

static int wsa881x_aclk_event(struct snd_soc_dapm_widget *w,
			      struct snd_kcontrol *kcontrol, int event)
{
	struct snd_soc_component *comp = snd_soc_dapm_to_component(w->dapm);
	struct wsa881x_priv *wsa881x = snd_soc_component_get_drvdata(comp);

	return wsa881x_update_bits(wsa881x, WSA881X_CDC_ANA_CLK_CTL, BIT(0),
				     event == SND_SOC_DAPM_PRE_PMU ? BIT(0) : 0);
}

static const struct snd_soc_dapm_widget wsa881x_dapm_widgets[] = {
	SND_SOC_DAPM_INPUT("IN"),
	SND_SOC_DAPM_DAC_E("RDAC", NULL, SND_SOC_NOPM, 0, 0,
			   wsa881x_rdac_event,
			   SND_SOC_DAPM_PRE_PMU | SND_SOC_DAPM_POST_PMD),
	SND_SOC_DAPM_PGA_E("SPKR PGA", SND_SOC_NOPM, 0, 0, NULL, 0,
			   wsa881x_spkr_pa_event, SND_SOC_DAPM_PRE_PMU |
			   SND_SOC_DAPM_POST_PMU | SND_SOC_DAPM_POST_PMD),
	SND_SOC_DAPM_SUPPLY("DCLK", SND_SOC_NOPM, 0, 0, wsa881x_dclk_event,
			    SND_SOC_DAPM_PRE_PMU | SND_SOC_DAPM_POST_PMD),
	SND_SOC_DAPM_SUPPLY("ACLK", SND_SOC_NOPM, 0, 0, wsa881x_aclk_event,
			    SND_SOC_DAPM_PRE_PMU | SND_SOC_DAPM_POST_PMD),
	SND_SOC_DAPM_SUPPLY("Bandgap", SND_SOC_NOPM, 0, 0,
			    wsa881x_bandgap_event,
			    SND_SOC_DAPM_PRE_PMU | SND_SOC_DAPM_POST_PMD),
	SND_SOC_DAPM_OUTPUT("SPKR"),
};

static int wsa881x_hw_params(struct snd_pcm_substream *substream,
			     struct snd_pcm_hw_params *params,
			     struct snd_soc_dai *dai)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(dai->dev);
	int i, ret;

	mutex_lock(&wsa881x->spx_state_lock);
	if (spx_enumerated_mode && wsa881x->slave->dev_num >= 1 &&
	    wsa881x->slave->dev_num <= 2) {
		if (spx_swap_dac_master_ports)
			wsa881x->slave->m_port_map[WSA881X_PORT_DAC + 1] =
				wsa881x->slave->dev_num == 1 ? 4 : 1;
		else
			wsa881x->slave->m_port_map[WSA881X_PORT_DAC + 1] =
				wsa881x->slave->dev_num == 1 ? 1 : 4;
		dev_info(wsa881x->dev,
			 "SPX: device=%u DAC slave port 1 -> master DP%u (swap=%u)\n",
			 wsa881x->slave->dev_num,
			 wsa881x->slave->m_port_map[WSA881X_PORT_DAC + 1],
			 spx_swap_dac_master_ports);
	}
	/*
	 * SPX: module parameters are writable, but the original override was
	 * consumed only once at probe.  Refresh it for every new stream so an
	 * isolated amplifier can sweep slave ports without a reboot per map.
	 */
	if (wsa881x->spx_write_only) {
		for (i = 0; i < spx_port_map_count &&
		     i < WSA881X_MAX_SWR_PORTS; i++) {
			if (spx_port_map[i] > 0)
				wsa881x->slave->m_port_map[i + 1] =
					spx_port_map[i];
		}
		dev_info(wsa881x->dev,
			 "SPX: live port map slave1..4 -> master %u %u %u %u\n",
			 wsa881x->slave->m_port_map[1],
			 wsa881x->slave->m_port_map[2],
			 wsa881x->slave->m_port_map[3],
			 wsa881x->slave->m_port_map[4]);
	}
	wsa881x->active_ports = 0;
	WRITE_ONCE(wsa881x->spx_stream_configured, false);
	if (!wsa881x_spx_transport_enabled(wsa881x)) {
		dev_info(wsa881x->dev,
			 "SPX: device=%u excluded from this stream\n",
			 wsa881x->slave->dev_num);
		mutex_unlock(&wsa881x->spx_state_lock);
		return 0;
	}
	for (i = 0; i < WSA881X_MAX_SWR_PORTS; i++) {
		if (wsa881x->spx_write_only || spx_enumerated_mode) {
			/*
			 * Keep the experimental transport mask independent from
			 * analog controls. The guarded baseline selects DAC only;
			 * COMP/VISENSE remain off and BOOST is an analog supply.
			 */
			if (!(spx_stream_port_mask & BIT(i)))
				continue;
		} else if (!wsa881x->port_enable[i]) {
			continue;
		}

		wsa881x->port_config[wsa881x->active_ports] =
							wsa881x_pconfig[i];
		wsa881x->active_ports++;
	}
	if (wsa881x->spx_write_only || spx_enumerated_mode)
		dev_info(wsa881x->dev,
			 "SPX: device=%u hw_params active_ports=%d\n",
			 wsa881x->slave->dev_num, wsa881x->active_ports);

	ret = sdw_stream_add_slave(wsa881x->slave, &wsa881x->sconfig,
				   wsa881x->port_config, wsa881x->active_ports,
				   wsa881x->sruntime);
	if (!ret)
		WRITE_ONCE(wsa881x->spx_stream_configured, true);
	mutex_unlock(&wsa881x->spx_state_lock);
	return ret;
}

static int wsa881x_hw_free(struct snd_pcm_substream *substream,
			   struct snd_soc_dai *dai)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(dai->dev);

	mutex_lock(&wsa881x->spx_state_lock);
	if (READ_ONCE(wsa881x->spx_stream_configured)) {
		sdw_stream_remove_slave(wsa881x->slave, wsa881x->sruntime);
		WRITE_ONCE(wsa881x->spx_stream_configured, false);
	}
	mutex_unlock(&wsa881x->spx_state_lock);

	return 0;
}

static int wsa881x_set_sdw_stream(struct snd_soc_dai *dai,
				  void *stream, int direction)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(dai->dev);

	wsa881x->sruntime = stream;

	return 0;
}

static int wsa881x_digital_mute(struct snd_soc_dai *dai, int mute, int stream)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(dai->dev);

	if (mute || !wsa881x_spx_transport_enabled(wsa881x))
		return wsa881x_update_bits(wsa881x, WSA881X_SPKR_DRV_EN,
					    0x80, 0x00);

	return wsa881x_update_bits(wsa881x, WSA881X_SPKR_DRV_EN,
				    0x80, 0x80);
}

static const struct snd_soc_dai_ops wsa881x_dai_ops = {
	.hw_params = wsa881x_hw_params,
	.hw_free = wsa881x_hw_free,
	.mute_stream = wsa881x_digital_mute,
	.set_stream = wsa881x_set_sdw_stream,
};

static struct snd_soc_dai_driver wsa881x_dais[] = {
	{
		.name = "SPKR",
		.id = 0,
		.playback = {
			.stream_name = "SPKR Playback",
			.rates = SNDRV_PCM_RATE_48000,
			.formats = SNDRV_PCM_FMTBIT_S16_LE,
			.rate_max = 48000,
			.rate_min = 48000,
			.channels_min = 1,
			.channels_max = 1,
		},
		.ops = &wsa881x_dai_ops,
	},
};

static const struct snd_soc_component_driver wsa881x_component_drv = {
	.name = "WSA881x",
	.probe = wsa881x_component_probe,
	.controls = wsa881x_snd_controls,
	.num_controls = ARRAY_SIZE(wsa881x_snd_controls),
	.dapm_widgets = wsa881x_dapm_widgets,
	.num_dapm_widgets = ARRAY_SIZE(wsa881x_dapm_widgets),
	.dapm_routes = wsa881x_audio_map,
	.num_dapm_routes = ARRAY_SIZE(wsa881x_audio_map),
	.endianness = 1,
};

static int wsa881x_update_status(struct sdw_slave *slave,
				 enum sdw_slave_status status)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(&slave->dev);

	if (status == SDW_SLAVE_ATTACHED && slave->dev_num > 0)
		return wsa881x_init(wsa881x);

	return 0;
}

static int wsa881x_port_prep(struct sdw_slave *slave,
			     struct sdw_prepare_ch *prepare_ch,
			     enum sdw_port_prep_ops state)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(&slave->dev);

	mutex_lock(&wsa881x->spx_state_lock);
	if (state == SDW_OPS_PORT_POST_PREP)
		wsa881x->port_prepared[prepare_ch->num - 1] = true;
	else
		wsa881x->port_prepared[prepare_ch->num - 1] = false;
	mutex_unlock(&wsa881x->spx_state_lock);

	return 0;
}

static int wsa881x_bus_config(struct sdw_slave *slave,
				      struct sdw_bus_params *params)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(&slave->dev);

	if (!wsa881x_spx_transport_enabled(wsa881x))
		return 0;
	sdw_write(slave, SWRS_SCP_HOST_CLK_DIV2_CTL_BANK(params->next_bank),
		  0x01);

	return 0;
}

static const struct sdw_slave_ops wsa881x_slave_ops = {
	.update_status = wsa881x_update_status,
	.bus_config = wsa881x_bus_config,
	.port_prep = wsa881x_port_prep,
};

static int wsa881x_probe(struct sdw_slave *pdev,
			 const struct sdw_device_id *id)
{
	int pm;
	struct wsa881x_priv *wsa881x;
	struct device *dev = &pdev->dev;

	/*
	 * SPX: refuse to bind to a DT-disabled speaker node. The SoundWire core
	 * still creates a device for it, and since each amp now drives its OWN
	 * powerdown pin, probing the disabled node powers the second amplifier.
	 * Both amps then sit unenumerated at device 0 and collide, so nothing
	 * enumerates at all (MCP_SLV_STATUS reads 0x0). This was harmless only
	 * while both nodes wrongly shared pin 1.
	 */
	if (dev->of_node && !of_device_is_available(dev->of_node)) {
		dev_info(dev, "SPX: node disabled in DT, not binding\n");
		return -ENODEV;
	}

	wsa881x = devm_kzalloc(dev, sizeof(*wsa881x), GFP_KERNEL);
	if (!wsa881x)
		return -ENOMEM;
	mutex_init(&wsa881x->spx_shadow_lock);
	mutex_init(&wsa881x->spx_state_lock);

	/*
	 * With native hardware enumeration each Surface amp has a distinct
	 * logical device number, so reads do not collide, and the normal
	 * WSA881x regmap/init path matches the Windows cold-start sequence --
	 * hence the default of false.
	 *
	 * The older single-amp bring-up (the spx-wsa-pin2-test GRUB entry, the
	 * only configuration ever observed to produce sound) needs this true:
	 * it also selects the SD_N-via-WCD-regmap path instead of gpiolib, the
	 * write-only port config, and spx_rearm_init. Read at probe, so set it
	 * before the card is brought up:
	 *   modprobe snd_soc_wsa881x spx_write_only=1
	 */
	wsa881x->spx_write_only = spx_write_only;

	if (wsa881x->spx_write_only) {
		/*
		 * SPX: do NOT request the powerdown GPIO through gpiolib. The
		 * wcd934x gpiochip's owner-module refcount wedged negative on
		 * this platform, so every gpiod_request() returns EPROBE_DEFER
		 * and this driver defers forever. The SD_N line is driven via
		 * the WCD9340 SLIMbus regmap instead; walk up the parent chain
		 * (slave -> soundwire bus -> soundwire platform -> wcd934x
		 * codec) until a device with a regmap is found.
		 */
		struct of_phandle_args args;
		struct device *anc;

		for (anc = pdev->dev.parent; anc; anc = anc->parent) {
			wsa881x->spx_wcd_regmap = dev_get_regmap(anc, NULL);
			if (wsa881x->spx_wcd_regmap)
				break;
		}
		if (!wsa881x->spx_wcd_regmap)
			dev_warn(dev, "SPX: WCD regmap unavailable, SD_N not drivable\n");
		wsa881x->sd_n = NULL;

		/*
		 * Take THIS amp's SD_N pin from its own powerdown-gpios rather
		 * than assuming a fixed pin, so the two amps are gated
		 * independently and can be brought up one at a time.
		 */
		wsa881x->spx_sd_n_pin = SPX_WSA_SD_N_PIN_DFL;
		if (!of_parse_phandle_with_args(dev->of_node, "powerdown-gpios",
						"#gpio-cells", 0, &args)) {
			if (args.args_count > 0)
				wsa881x->spx_sd_n_pin = args.args[0];
			of_node_put(args.np);
		}
		dev_info(dev, "SPX: SD_N on wcd-gpio pin %d\n",
			 wsa881x->spx_sd_n_pin);
	} else {
		wsa881x->sd_n = devm_gpiod_get_optional(dev, "powerdown",
							GPIOD_FLAGS_BIT_NONEXCLUSIVE);
		if (IS_ERR(wsa881x->sd_n))
			return dev_err_probe(dev, PTR_ERR(wsa881x->sd_n),
					     "Shutdown Control GPIO not found\n");
	}

	/*
	 * Backwards compatibility work-around.
	 *
	 * The SD_N GPIO is active low, however upstream DTS used always active
	 * high.  Changing the flag in driver and DTS will break backwards
	 * compatibility, so add a simple value inversion to work with both old
	 * and new DTS.
	 *
	 * This won't work properly with DTS using the flags properly in cases:
	 * 1. Old DTS with proper ACTIVE_LOW, however such case was broken
	 *    before as the driver required the active high.
	 * 2. New DTS with proper ACTIVE_HIGH (intended), which is rare case
	 *    (not existing upstream) but possible. This is the price of
	 *    backwards compatibility, therefore this hack should be removed at
	 *    some point.
	 */
	wsa881x->sd_n_val = wsa881x->sd_n ?
		gpiod_is_active_low(wsa881x->sd_n) : 1;
	if (!wsa881x->sd_n_val)
		dev_warn(dev, "Using ACTIVE_HIGH for shutdown GPIO. Your DTB might be outdated or you use unsupported configuration for the GPIO.");

	dev_set_drvdata(dev, wsa881x);
	wsa881x->slave = pdev;
	wsa881x->dev = dev;
	wsa881x->sconfig.ch_count = 1;
	wsa881x->sconfig.bps = 1;
	wsa881x->sconfig.frame_rate = 48000;
	wsa881x->sconfig.direction = SDW_DATA_DIR_RX;
	wsa881x->sconfig.type = SDW_STREAM_PDM;
	if (wsa881x->spx_write_only || spx_enumerated_mode) {
		pdev->prop.quirks |= SDW_SLAVE_QUIRKS_WRITE_ONLY_PORTCTRL;
	}
	/* Keep each slave data port on the matching Qualcomm master port.
	 * In particular, WSA881x BOOST port 3 must not be dynamically packed
	 * onto COMP master port 2, which has different transport timing.
	 */
	if (of_property_read_u32_array(dev->of_node, "qcom,port-mapping",
				       &pdev->m_port_map[1],
				       WSA881X_MAX_SWR_PORTS))
		dev_dbg(dev, "Static port mapping not specified\n");

	/* SPX: runtime override of the above, see spx_port_map. */
	for (pm = 0; pm < spx_port_map_count && pm < WSA881X_MAX_SWR_PORTS; pm++) {
		if (spx_port_map[pm] > 0)
			pdev->m_port_map[pm + 1] = spx_port_map[pm];
	}
	dev_info(dev, "SPX: port map slave1..4 -> master %u %u %u %u\n",
		 pdev->m_port_map[1], pdev->m_port_map[2],
		 pdev->m_port_map[3], pdev->m_port_map[4]);
	pdev->prop.sink_ports = GENMASK(WSA881X_MAX_SWR_PORTS - 1, 0);
	pdev->prop.sink_dpn_prop = wsa_sink_dpn_prop;
	pdev->prop.scp_int1_mask =
		(wsa881x->spx_write_only || spx_enumerated_mode) ? 0 :
		SDW_SCP_INT1_BUS_CLASH | SDW_SCP_INT1_PARITY;
	pdev->prop.clk_stop_mode1 = true;
	/* Keep the SPX value runtime-adjustable while the bus polarity is being
	 * validated. Logical 0 is physical high for the active-low descriptor.
	 */
	if (wsa881x->spx_write_only)
		spx_wsa_powerdown_set(wsa881x, spx_powerdown_gpio);
	else if (wsa881x->sd_n &&
		 of_machine_is_compatible("microsoft,surface-pro-x"))
		/*
		 * The exact Windows path does not drive these through the WCD
		 * GPIO block. Preserve the firmware-established levels.
		 */
		dev_dbg(dev, "SPX: preserving firmware WSA control levels\n");
	else if (wsa881x->sd_n)
		gpiod_direction_output(wsa881x->sd_n, !wsa881x->sd_n_val);

	wsa881x->regmap = devm_regmap_init_sdw(pdev, &wsa881x_regmap_config);
	if (IS_ERR(wsa881x->regmap))
		return dev_err_probe(dev, PTR_ERR(wsa881x->regmap), "regmap_init failed\n");

	/*
	 * SPX: the shadow is needed by the blind read-modify-write path, which
	 * is now used in the enumerated configuration too (the master's read
	 * FIFO underflows), so allocate and seed it unconditionally.
	 */
	{
		int i;

		wsa881x->spx_reg_shadow = devm_kzalloc(dev,
				WSA881X_SPKR_STATUS3 + 1, GFP_KERNEL);
		if (!wsa881x->spx_reg_shadow)
			return -ENOMEM;
		for (i = 0; i < ARRAY_SIZE(wsa881x_defaults); i++)
			wsa881x->spx_reg_shadow[wsa881x_defaults[i].reg] =
				wsa881x_defaults[i].def;
		for (i = 0; i < ARRAY_SIZE(wsa881x_rev_2_0); i++)
			wsa881x->spx_reg_shadow[wsa881x_rev_2_0[i].reg] =
				wsa881x_rev_2_0[i].def;
	}

	pm_runtime_set_autosuspend_delay(dev, 3000);
	pm_runtime_use_autosuspend(dev);
	pm_runtime_mark_last_busy(dev);
	pm_runtime_set_active(dev);
	pm_runtime_enable(dev);
	/*
	 * SPX: runtime suspend asserts the (shared!) shutdown GPIO; resume
	 * then needs a SoundWire re-enumeration, which fails on the polled
	 * wcd934x master (AUTO_ENUM_FAILED) and latches a permanent
	 * runtime-PM error. The amps enumerate fine once at boot - keep
	 * them powered.
	 */
	pm = devm_snd_soc_register_component(dev, &wsa881x_component_drv,
					      wsa881x_dais,
					      ARRAY_SIZE(wsa881x_dais));
	if (pm)
		return pm;
	if (wsa881x->spx_write_only || spx_enumerated_mode)
		pm_runtime_forbid(dev);

	mutex_lock(&spx_debug_lock);
	if (of_device_is_available(dev->of_node) && !spx_debug_wsa881x) {
		spx_debug_wsa881x = wsa881x;
		spx_powerdown_desc = wsa881x->sd_n;
	}
	mutex_unlock(&spx_debug_lock);

	return 0;
}

static int wsa881x_remove(struct sdw_slave *pdev)
{
	struct wsa881x_priv *wsa881x = dev_get_drvdata(&pdev->dev);

	mutex_lock(&spx_debug_lock);
	if (spx_debug_wsa881x == wsa881x) {
		spx_debug_wsa881x = NULL;
		spx_powerdown_desc = NULL;
	}
	mutex_unlock(&spx_debug_lock);

	if (wsa881x->spx_write_only || spx_enumerated_mode)
		pm_runtime_allow(&pdev->dev);

	return 0;
}

static int wsa881x_runtime_suspend(struct device *dev)
{
	struct regmap *regmap = dev_get_regmap(dev, NULL);
	struct wsa881x_priv *wsa881x = dev_get_drvdata(dev);

	if (wsa881x->spx_write_only)
		spx_wsa_powerdown_set(wsa881x, 1);
	else if (wsa881x->sd_n)
		gpiod_direction_output(wsa881x->sd_n, wsa881x->sd_n_val);

	regcache_cache_only(regmap, true);
	regcache_mark_dirty(regmap);

	return 0;
}

static int wsa881x_runtime_resume(struct device *dev)
{
	struct sdw_slave *slave = dev_to_sdw_dev(dev);
	struct regmap *regmap = dev_get_regmap(dev, NULL);
	struct wsa881x_priv *wsa881x = dev_get_drvdata(dev);
	unsigned long time;

	if (wsa881x->spx_write_only)
		spx_wsa_powerdown_set(wsa881x, 0);
	else if (wsa881x->sd_n)
		gpiod_direction_output(wsa881x->sd_n, !wsa881x->sd_n_val);

	time = wait_for_completion_timeout(&slave->initialization_complete,
					   msecs_to_jiffies(WSA881X_PROBE_TIMEOUT));
	if (!time) {
		dev_err(dev, "Initialization not complete, timed out\n");
		if (wsa881x->spx_write_only)
			spx_wsa_powerdown_set(wsa881x, 1);
		else if (wsa881x->sd_n)
			gpiod_direction_output(wsa881x->sd_n, wsa881x->sd_n_val);
		return -ETIMEDOUT;
	}

	regcache_cache_only(regmap, false);
	regcache_sync(regmap);

	return 0;
}

static const struct dev_pm_ops wsa881x_pm_ops = {
	RUNTIME_PM_OPS(wsa881x_runtime_suspend, wsa881x_runtime_resume, NULL)
};

static const struct sdw_device_id wsa881x_slave_id[] = {
	SDW_SLAVE_ENTRY(0x0217, 0x2010, 0),
	SDW_SLAVE_ENTRY(0x0217, 0x2110, 0),
	{},
};
MODULE_DEVICE_TABLE(sdw, wsa881x_slave_id);

static struct sdw_driver wsa881x_codec_driver = {
	.probe	= wsa881x_probe,
	.remove = wsa881x_remove,
	.ops = &wsa881x_slave_ops,
	.id_table = wsa881x_slave_id,
	.driver = {
		.name	= "wsa881x-codec",
		.pm = pm_ptr(&wsa881x_pm_ops),
	}
};
module_sdw_driver(wsa881x_codec_driver);

MODULE_DESCRIPTION("WSA881x codec driver");
MODULE_LICENSE("GPL v2");
