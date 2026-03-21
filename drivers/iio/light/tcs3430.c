// SPDX-License-Identifier: GPL-2.0-only
/*
 * tcs3430.c - Support for AMS TCS3430 XYZ color and ambient light sensor
 *
 * Copyright (c) 2026 linux-surface contributors
 *
 * The TCS3430 is a 4-channel tristimulus XYZ color sensor with IR channel
 * at I2C address 0x39. It provides:
 *   - Channel 0 (X): CIE XYZ X-channel
 *   - Channel 1 (Y): CIE XYZ Y-channel (correlates to luminance)
 *   - Channel 2 (Z): CIE XYZ Z-channel
 *   - Channel 3 (IR): Infrared channel
 *
 * Datasheet: https://ams.com/tcs3430
 *
 * Known users:
 *   - Microsoft Surface Pro X (SC8180X, I2C2, address 0x39, IRQ GPIO24)
 */

#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/pm.h>

#include <linux/iio/buffer.h>
#include <linux/iio/events.h>
#include <linux/iio/iio.h>
#include <linux/iio/sysfs.h>
#include <linux/iio/trigger_consumer.h>
#include <linux/iio/triggered_buffer.h>

#define TCS3430_DRV_NAME "tcs3430"

/* Register map */
#define TCS3430_REG_ENABLE	0x80
#define TCS3430_REG_ATIME	0x81
#define TCS3430_REG_WTIME	0x83
#define TCS3430_REG_AILTL	0x84
#define TCS3430_REG_AILTH	0x85
#define TCS3430_REG_AIHTL	0x86
#define TCS3430_REG_AIHTH	0x87
#define TCS3430_REG_PERS	0x8C
#define TCS3430_REG_CFG0	0x8D
#define TCS3430_REG_CFG1	0x90
#define TCS3430_REG_REVID	0x91
#define TCS3430_REG_ID		0x92
#define TCS3430_REG_STATUS	0x93
#define TCS3430_REG_CH0DATAL	0x94	/* X channel low byte */
#define TCS3430_REG_CH1DATAL	0x96	/* Y channel low byte */
#define TCS3430_REG_CH2DATAL	0x98	/* Z channel low byte */
#define TCS3430_REG_CH3DATAL	0x9A	/* IR channel low byte */
#define TCS3430_REG_CFG2	0x9F
#define TCS3430_REG_CFG3	0xAB
#define TCS3430_REG_AZ_CONFIG	0xD6
#define TCS3430_REG_INTENAB	0xDD

/* ENABLE register bits */
#define TCS3430_ENABLE_PON	BIT(0)	/* Power ON */
#define TCS3430_ENABLE_AEN	BIT(1)	/* ALS Enable */
#define TCS3430_ENABLE_WEN	BIT(3)	/* Wait Enable */
#define TCS3430_ENABLE_AIEN	BIT(4)	/* ALS Interrupt Enable (legacy) */

/* STATUS register bits */
#define TCS3430_STATUS_AVALID	BIT(0)	/* ALS data valid */
#define TCS3430_STATUS_ASAT	BIT(7)	/* ALS saturation */
#define TCS3430_STATUS_AINT	BIT(4)	/* ALS interrupt */

/* CFG1 register bits - gain control */
#define TCS3430_CFG1_AGAIN_MASK	(BIT(0) | BIT(1))
#define TCS3430_CFG1_AGAIN_1X	0x00
#define TCS3430_CFG1_AGAIN_4X	0x01
#define TCS3430_CFG1_AGAIN_16X	0x02
#define TCS3430_CFG1_AGAIN_64X	0x03

/* CFG2 register bits */
#define TCS3430_CFG2_HGAIN	BIT(2)	/* High gain (128x) */

/* INTENAB register bits */
#define TCS3430_INTENAB_AIEN	BIT(4)	/* ALS interrupt enable */

/* Chip ID */
#define TCS3430_CHIP_ID		0xDC

/*
 * Integration time: ATIME register.
 * Time = (256 - ATIME) * 2.78 ms
 * 0xFF = 2.78 ms (minimum), 0x00 = 711 ms (maximum)
 * We use microseconds internally: 2780 us per step.
 */
#define TCS3430_ATIME_STEP_US	2780

struct tcs3430_data {
	struct i2c_client *client;
	struct mutex lock;
	u8 enable;
	u8 cfg1;
	u8 atime;
	u16 low_thresh;
	u16 high_thresh;
	u8 apers;
};

/*
 * Gain table: index maps to CFG1.AGAIN bits.
 * 128x gain is controlled separately via CFG2.HGAIN and not included here
 * to keep the gain setting simple and matching the AGAIN field directly.
 */
static const int tcs3430_again[] = { 1, 4, 16, 64 };

static const struct iio_event_spec tcs3430_events[] = {
	{
		.type = IIO_EV_TYPE_THRESH,
		.dir = IIO_EV_DIR_RISING,
		.mask_separate = BIT(IIO_EV_INFO_VALUE),
	},
	{
		.type = IIO_EV_TYPE_THRESH,
		.dir = IIO_EV_DIR_FALLING,
		.mask_separate = BIT(IIO_EV_INFO_VALUE),
	},
	{
		.type = IIO_EV_TYPE_THRESH,
		.dir = IIO_EV_DIR_EITHER,
		.mask_separate = BIT(IIO_EV_INFO_ENABLE) |
				 BIT(IIO_EV_INFO_PERIOD),
	},
};

/*
 * Channel 0 is X (with threshold events tied to the ALS interrupt).
 * Channels 1-3 are Y, Z, IR.
 */
#define TCS3430_CHANNEL(_mod, _si, _addr, _ev, _nev)		\
{								\
	.type = IIO_INTENSITY,					\
	.modified = 1,						\
	.channel2 = IIO_MOD_LIGHT_##_mod,			\
	.address = _addr,					\
	.scan_index = _si,					\
	.scan_type = {						\
		.sign = 'u',					\
		.realbits = 16,					\
		.storagebits = 16,				\
		.endianness = IIO_CPU,				\
	},							\
	.info_mask_separate = BIT(IIO_CHAN_INFO_RAW),		\
	.info_mask_shared_by_type = BIT(IIO_CHAN_INFO_CALIBSCALE) | \
				    BIT(IIO_CHAN_INFO_INT_TIME),	\
	.event_spec = _ev,					\
	.num_event_specs = _nev,				\
}

static const struct iio_chan_spec tcs3430_channels[] = {
	/* X tristimulus - also used for ALS threshold interrupts */
	TCS3430_CHANNEL(X, 0, TCS3430_REG_CH0DATAL,
			tcs3430_events, ARRAY_SIZE(tcs3430_events)),
	/* Y tristimulus (correlates to CIE Y / luminance) */
	TCS3430_CHANNEL(Y, 1, TCS3430_REG_CH1DATAL, NULL, 0),
	/* Z tristimulus */
	TCS3430_CHANNEL(Z, 2, TCS3430_REG_CH2DATAL, NULL, 0),
	/* Infrared */
	TCS3430_CHANNEL(IR, 3, TCS3430_REG_CH3DATAL, NULL, 0),
	IIO_CHAN_SOFT_TIMESTAMP(4),
};

static int tcs3430_wait_data_ready(struct tcs3430_data *data)
{
	int tries = 50;
	int ret;

	while (tries--) {
		ret = i2c_smbus_read_byte_data(data->client, TCS3430_REG_STATUS);
		if (ret < 0)
			return ret;
		if (ret & TCS3430_STATUS_AVALID)
			return 0;
		msleep(20);
	}

	dev_err(&data->client->dev, "ALS data not ready\n");
	return -EIO;
}

static int tcs3430_read_raw(struct iio_dev *indio_dev,
			    struct iio_chan_spec const *chan,
			    int *val, int *val2, long mask)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	int ret;

	switch (mask) {
	case IIO_CHAN_INFO_RAW:
		if (!iio_device_claim_direct(indio_dev))
			return -EBUSY;
		ret = tcs3430_wait_data_ready(data);
		if (ret < 0) {
			iio_device_release_direct(indio_dev);
			return ret;
		}
		ret = i2c_smbus_read_word_data(data->client, chan->address);
		iio_device_release_direct(indio_dev);
		if (ret < 0)
			return ret;
		*val = ret;
		return IIO_VAL_INT;

	case IIO_CHAN_INFO_CALIBSCALE:
		*val = tcs3430_again[data->cfg1 & TCS3430_CFG1_AGAIN_MASK];
		return IIO_VAL_INT;

	case IIO_CHAN_INFO_INT_TIME:
		*val = 0;
		*val2 = (256 - data->atime) * TCS3430_ATIME_STEP_US;
		return IIO_VAL_INT_PLUS_MICRO;
	}

	return -EINVAL;
}

static int tcs3430_write_raw(struct iio_dev *indio_dev,
			     struct iio_chan_spec const *chan,
			     int val, int val2, long mask)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	int i, ret;

	switch (mask) {
	case IIO_CHAN_INFO_CALIBSCALE:
		if (val2 != 0)
			return -EINVAL;
		for (i = 0; i < ARRAY_SIZE(tcs3430_again); i++) {
			if (val != tcs3430_again[i])
				continue;
			mutex_lock(&data->lock);
			data->cfg1 = (data->cfg1 & ~TCS3430_CFG1_AGAIN_MASK) | i;
			ret = i2c_smbus_write_byte_data(data->client,
							TCS3430_REG_CFG1,
							data->cfg1);
			mutex_unlock(&data->lock);
			return ret;
		}
		return -EINVAL;

	case IIO_CHAN_INFO_INT_TIME:
		if (val != 0)
			return -EINVAL;
		for (i = 0; i < 256; i++) {
			if (val2 != (256 - i) * TCS3430_ATIME_STEP_US)
				continue;
			mutex_lock(&data->lock);
			data->atime = i;
			ret = i2c_smbus_write_byte_data(data->client,
							TCS3430_REG_ATIME,
							data->atime);
			mutex_unlock(&data->lock);
			return ret;
		}
		return -EINVAL;
	}

	return -EINVAL;
}

/*
 * ALS persistence filter: number of consecutive out-of-range readings
 * before an interrupt fires. Index is the PERS field value (0-15).
 */
static const int tcs3430_pers[] = {
	0, 1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60
};

static int tcs3430_read_event(struct iio_dev *indio_dev,
			      const struct iio_chan_spec *chan,
			      enum iio_event_type type,
			      enum iio_event_direction dir,
			      enum iio_event_info info,
			      int *val, int *val2)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	unsigned int period;
	int ret;

	mutex_lock(&data->lock);
	switch (info) {
	case IIO_EV_INFO_VALUE:
		*val = (dir == IIO_EV_DIR_RISING) ?
			data->high_thresh : data->low_thresh;
		ret = IIO_VAL_INT;
		break;
	case IIO_EV_INFO_PERIOD:
		period = (256 - data->atime) * TCS3430_ATIME_STEP_US *
			 tcs3430_pers[data->apers];
		*val = period / USEC_PER_SEC;
		*val2 = period % USEC_PER_SEC;
		ret = IIO_VAL_INT_PLUS_MICRO;
		break;
	default:
		ret = -EINVAL;
		break;
	}
	mutex_unlock(&data->lock);

	return ret;
}

static int tcs3430_write_event(struct iio_dev *indio_dev,
			       const struct iio_chan_spec *chan,
			       enum iio_event_type type,
			       enum iio_event_direction dir,
			       enum iio_event_info info,
			       int val, int val2)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	int period, i, ret;
	u8 reg;

	mutex_lock(&data->lock);
	switch (info) {
	case IIO_EV_INFO_VALUE:
		if (dir == IIO_EV_DIR_RISING) {
			reg = TCS3430_REG_AIHTL;
			data->high_thresh = val;
		} else if (dir == IIO_EV_DIR_FALLING) {
			reg = TCS3430_REG_AILTL;
			data->low_thresh = val;
		} else {
			ret = -EINVAL;
			goto out;
		}
		ret = i2c_smbus_write_word_data(data->client, reg, val);
		break;
	case IIO_EV_INFO_PERIOD:
		period = val * USEC_PER_SEC + val2;
		for (i = 1; i < ARRAY_SIZE(tcs3430_pers) - 1; i++) {
			if (period <= (256 - data->atime) *
				      TCS3430_ATIME_STEP_US *
				      tcs3430_pers[i])
				break;
		}
		ret = i2c_smbus_write_byte_data(data->client,
						TCS3430_REG_PERS, i);
		if (!ret)
			data->apers = i;
		break;
	default:
		ret = -EINVAL;
		break;
	}
out:
	mutex_unlock(&data->lock);
	return ret;
}

static int tcs3430_read_event_config(struct iio_dev *indio_dev,
				     const struct iio_chan_spec *chan,
				     enum iio_event_type type,
				     enum iio_event_direction dir)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	int ret;

	mutex_lock(&data->lock);
	ret = !!(data->enable & TCS3430_ENABLE_AIEN);
	mutex_unlock(&data->lock);

	return ret;
}

static int tcs3430_write_event_config(struct iio_dev *indio_dev,
				      const struct iio_chan_spec *chan,
				      enum iio_event_type type,
				      enum iio_event_direction dir,
				      bool state)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	u8 enable_old;
	int ret = 0;

	mutex_lock(&data->lock);
	enable_old = data->enable;

	if (state)
		data->enable |= TCS3430_ENABLE_AIEN;
	else
		data->enable &= ~TCS3430_ENABLE_AIEN;

	if (enable_old != data->enable) {
		ret = i2c_smbus_write_byte_data(data->client,
						TCS3430_REG_ENABLE,
						data->enable);
		if (ret)
			data->enable = enable_old;
	}
	mutex_unlock(&data->lock);

	return ret;
}

static irqreturn_t tcs3430_event_handler(int irq, void *priv)
{
	struct iio_dev *indio_dev = priv;
	struct tcs3430_data *data = iio_priv(indio_dev);
	int ret;

	ret = i2c_smbus_read_byte_data(data->client, TCS3430_REG_STATUS);
	if (ret >= 0 && (ret & TCS3430_STATUS_AINT)) {
		iio_push_event(indio_dev,
			       IIO_UNMOD_EVENT_CODE(IIO_INTENSITY, 0,
						    IIO_EV_TYPE_THRESH,
						    IIO_EV_DIR_EITHER),
			       iio_get_time_ns(indio_dev));

		/*
		 * Clear interrupt by writing to STATUS register.
		 * Per TCS3430 datasheet, writing 1 to AINT clears the flag.
		 */
		i2c_smbus_write_byte_data(data->client, TCS3430_REG_STATUS,
					  TCS3430_STATUS_AINT);
	}

	return IRQ_HANDLED;
}

static irqreturn_t tcs3430_trigger_handler(int irq, void *p)
{
	struct iio_poll_func *pf = p;
	struct iio_dev *indio_dev = pf->indio_dev;
	struct tcs3430_data *data = iio_priv(indio_dev);
	/* Ensure timestamp is naturally aligned */
	struct {
		u16 chans[4];
		aligned_s64 timestamp;
	} scan = { };
	int i, j = 0;
	int ret;

	ret = tcs3430_wait_data_ready(data);
	if (ret < 0)
		goto done;

	iio_for_each_active_channel(indio_dev, i) {
		/*
		 * Channels are at 0x94, 0x96, 0x98, 0x9A (2-byte spacing).
		 * scan_index matches channel order: 0=X, 1=Y, 2=Z, 3=IR.
		 */
		ret = i2c_smbus_read_word_data(data->client,
					       TCS3430_REG_CH0DATAL + 2 * i);
		if (ret < 0)
			goto done;
		scan.chans[j++] = ret;
	}

	iio_push_to_buffers_with_ts(indio_dev, &scan, sizeof(scan),
				    iio_get_time_ns(indio_dev));
done:
	iio_trigger_notify_done(indio_dev->trig);
	return IRQ_HANDLED;
}

static ssize_t tcs3430_show_int_time_available(struct device *dev,
					       struct device_attribute *attr,
					       char *buf)
{
	size_t len = 0;
	int i;

	for (i = 1; i <= 256; i++)
		len += scnprintf(buf + len, PAGE_SIZE - len, "0.%06d ",
				 TCS3430_ATIME_STEP_US * i);

	/* replace trailing space by newline */
	buf[len - 1] = '\n';

	return len;
}

static IIO_CONST_ATTR(calibscale_available, "1 4 16 64");
static IIO_DEV_ATTR_INT_TIME_AVAIL(tcs3430_show_int_time_available);

static struct attribute *tcs3430_attributes[] = {
	&iio_const_attr_calibscale_available.dev_attr.attr,
	&iio_dev_attr_integration_time_available.dev_attr.attr,
	NULL
};

static const struct attribute_group tcs3430_attribute_group = {
	.attrs = tcs3430_attributes,
};

static const struct iio_info tcs3430_info = {
	.read_raw = tcs3430_read_raw,
	.write_raw = tcs3430_write_raw,
	.read_event_value = tcs3430_read_event,
	.write_event_value = tcs3430_write_event,
	.read_event_config = tcs3430_read_event_config,
	.write_event_config = tcs3430_write_event_config,
	.attrs = &tcs3430_attribute_group,
};

static int tcs3430_powerup(struct tcs3430_data *data)
{
	int ret;

	mutex_lock(&data->lock);
	data->enable |= TCS3430_ENABLE_PON | TCS3430_ENABLE_AEN;
	ret = i2c_smbus_write_byte_data(data->client, TCS3430_REG_ENABLE,
					data->enable);
	mutex_unlock(&data->lock);
	return ret;
}

static int tcs3430_powerdown(struct tcs3430_data *data)
{
	int ret;

	mutex_lock(&data->lock);
	data->enable &= ~(TCS3430_ENABLE_PON | TCS3430_ENABLE_AEN);
	ret = i2c_smbus_write_byte_data(data->client, TCS3430_REG_ENABLE,
					data->enable);
	mutex_unlock(&data->lock);
	return ret;
}

static int tcs3430_probe(struct i2c_client *client)
{
	struct tcs3430_data *data;
	struct iio_dev *indio_dev;
	int ret;

	indio_dev = devm_iio_device_alloc(&client->dev, sizeof(*data));
	if (!indio_dev)
		return -ENOMEM;

	data = iio_priv(indio_dev);
	i2c_set_clientdata(client, indio_dev);
	data->client = client;
	mutex_init(&data->lock);

	/* Verify chip identity */
	ret = i2c_smbus_read_byte_data(client, TCS3430_REG_ID);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to read chip ID\n");
	if (ret != TCS3430_CHIP_ID)
		return dev_err_probe(&client->dev, -ENODEV,
				     "unexpected chip ID 0x%02x (expected 0x%02x)\n",
				     ret, TCS3430_CHIP_ID);

	dev_dbg(&client->dev, "TCS3430 found (ID=0x%02x)\n", ret);

	/* Read current CFG1 (gain) and ATIME */
	ret = i2c_smbus_read_byte_data(client, TCS3430_REG_CFG1);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to read CFG1\n");
	data->cfg1 = ret;

	ret = i2c_smbus_read_byte_data(client, TCS3430_REG_ATIME);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to read ATIME\n");
	data->atime = ret;

	/* Read current interrupt thresholds */
	ret = i2c_smbus_read_word_data(client, TCS3430_REG_AILTL);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to read low threshold\n");
	data->low_thresh = ret;

	ret = i2c_smbus_read_word_data(client, TCS3430_REG_AIHTL);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to read high threshold\n");
	data->high_thresh = ret;

	/* Set persistence to 1 cycle (minimum before interrupt fires) */
	data->apers = 1;
	ret = i2c_smbus_write_byte_data(client, TCS3430_REG_PERS, data->apers);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to set persistence\n");

	/* Power on with ALS enabled, no interrupt yet */
	data->enable = TCS3430_ENABLE_PON | TCS3430_ENABLE_AEN;
	ret = i2c_smbus_write_byte_data(client, TCS3430_REG_ENABLE,
					data->enable);
	if (ret < 0)
		return dev_err_probe(&client->dev, ret,
				     "failed to enable device\n");

	indio_dev->info = &tcs3430_info;
	indio_dev->name = TCS3430_DRV_NAME;
	indio_dev->channels = tcs3430_channels;
	indio_dev->num_channels = ARRAY_SIZE(tcs3430_channels);
	indio_dev->modes = INDIO_DIRECT_MODE;

	ret = iio_triggered_buffer_setup(indio_dev, NULL,
					 tcs3430_trigger_handler, NULL);
	if (ret < 0) {
		dev_err(&client->dev, "failed to set up triggered buffer\n");
		goto err_powerdown;
	}

	if (client->irq) {
		ret = request_threaded_irq(client->irq, NULL,
					   tcs3430_event_handler,
					   IRQF_TRIGGER_FALLING |
					   IRQF_SHARED | IRQF_ONESHOT,
					   client->name, indio_dev);
		if (ret) {
			dev_err(&client->dev, "failed to request IRQ %d\n",
				client->irq);
			goto err_buffer_cleanup;
		}
	}

	ret = iio_device_register(indio_dev);
	if (ret < 0) {
		dev_err(&client->dev, "failed to register IIO device\n");
		goto err_free_irq;
	}

	return 0;

err_free_irq:
	if (client->irq)
		free_irq(client->irq, indio_dev);
err_buffer_cleanup:
	iio_triggered_buffer_cleanup(indio_dev);
err_powerdown:
	tcs3430_powerdown(data);
	return ret;
}

static void tcs3430_remove(struct i2c_client *client)
{
	struct iio_dev *indio_dev = i2c_get_clientdata(client);

	iio_device_unregister(indio_dev);
	if (client->irq)
		free_irq(client->irq, indio_dev);
	iio_triggered_buffer_cleanup(indio_dev);
	tcs3430_powerdown(iio_priv(indio_dev));
}

static int tcs3430_suspend(struct device *dev)
{
	struct tcs3430_data *data =
		iio_priv(i2c_get_clientdata(to_i2c_client(dev)));

	return tcs3430_powerdown(data);
}

static int tcs3430_resume(struct device *dev)
{
	struct tcs3430_data *data =
		iio_priv(i2c_get_clientdata(to_i2c_client(dev)));

	return tcs3430_powerup(data);
}

static DEFINE_SIMPLE_DEV_PM_OPS(tcs3430_pm_ops, tcs3430_suspend,
				tcs3430_resume);

static const struct i2c_device_id tcs3430_id[] = {
	{ "tcs3430" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, tcs3430_id);

static const struct of_device_id tcs3430_of_match[] = {
	{ .compatible = "ams,tcs3430" },
	{ }
};
MODULE_DEVICE_TABLE(of, tcs3430_of_match);

static struct i2c_driver tcs3430_driver = {
	.driver = {
		.name		= TCS3430_DRV_NAME,
		.of_match_table	= tcs3430_of_match,
		.pm		= pm_sleep_ptr(&tcs3430_pm_ops),
	},
	.probe		= tcs3430_probe,
	.remove		= tcs3430_remove,
	.id_table	= tcs3430_id,
};
module_i2c_driver(tcs3430_driver);

MODULE_AUTHOR("linux-surface contributors");
MODULE_DESCRIPTION("AMS TCS3430 XYZ color and ambient light sensor driver");
MODULE_LICENSE("GPL");
