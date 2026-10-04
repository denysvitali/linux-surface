// SPDX-License-Identifier: GPL-2.0-only
/*
 * AMS TCS3430 CIE XYZ and infrared sensor.
 *
 * Raw optical channels only: illuminance needs optical calibration for the
 * assembled device. CH3 is kept on X, so the multiplexed IR2 is not exposed.
 * Datasheet: https://look.ams-osram.com/m/565e57ee81583733/original/TCS3430-DS000464.pdf
 */

#include <linux/bits.h>
#include <linux/cleanup.h>
#include <linux/i2c.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm_runtime.h>

#include <linux/iio/iio.h>

#define TCS3430_ENABLE		0x80
#define TCS3430_ATIME		0x81
#define TCS3430_PERS		0x8c
#define TCS3430_CFG0		0x8d
#define TCS3430_CFG1		0x90
#define TCS3430_ID		0x92
#define TCS3430_STATUS		0x93
#define TCS3430_Z		0x94
#define TCS3430_Y		0x96
#define TCS3430_IR1		0x98
#define TCS3430_X		0x9a
#define TCS3430_CFG2		0x9f
#define TCS3430_CFG3		0xab
#define TCS3430_AZ_CONFIG		0xd6
#define TCS3430_INTENAB		0xdd

#define TCS3430_PON		BIT(0)
#define TCS3430_AEN		BIT(1)
#define TCS3430_AINT		BIT(4)
#define TCS3430_ASAT		BIT(7)
#define TCS3430_ID_MASK		GENMASK(7, 2)
#define TCS3430_ID_VALUE		0xdc
#define TCS3430_TIME_STEP_US	2780
#define TCS3430_TIME_STEP_MAX_US	2920

struct tcs3430_data {
	struct i2c_client *client;
	struct mutex lock;
	u8 atime;
	u8 gain;
	bool needs_config;
};

#define TCS3430_CHANNEL(_modifier, _address) { \
	.type = IIO_INTENSITY, \
	.modified = 1, \
	.channel2 = IIO_MOD_##_modifier, \
	.address = _address, \
	.info_mask_separate = BIT(IIO_CHAN_INFO_RAW), \
	.info_mask_shared_by_type = BIT(IIO_CHAN_INFO_HARDWAREGAIN) | \
		BIT(IIO_CHAN_INFO_INT_TIME), \
	.info_mask_shared_by_type_available = BIT(IIO_CHAN_INFO_HARDWAREGAIN) | \
		BIT(IIO_CHAN_INFO_INT_TIME), \
	.scan_index = -1, \
}

static const struct iio_chan_spec tcs3430_channels[] = {
	TCS3430_CHANNEL(X, TCS3430_X),
	TCS3430_CHANNEL(Y, TCS3430_Y),
	TCS3430_CHANNEL(Z, TCS3430_Z),
	TCS3430_CHANNEL(LIGHT_IR, TCS3430_IR1),
};

static const int tcs3430_gains[] = { 1, 4, 16, 64 };
static const int tcs3430_times[] = {
	0, TCS3430_TIME_STEP_US,
	0, TCS3430_TIME_STEP_US,
	0, 256 * TCS3430_TIME_STEP_US,
};

/* Caller holds lock. Configuration changes take effect before the next read. */
static int tcs3430_start(struct tcs3430_data *data)
{
	struct i2c_client *client = data->client;
	const u8 config[][2] = {
		{ TCS3430_ENABLE, 0 },
		{ TCS3430_INTENAB, 0 },
		{ TCS3430_ATIME, data->atime },
		{ TCS3430_CFG0, 0x80 }, /* Reserved bits, no wait extension. */
		{ TCS3430_CFG1, data->gain }, /* AMUX = 0 selects X. */
		{ TCS3430_CFG2, 0x04 }, /* Reserved bits, no 128x gain. */
		{ TCS3430_CFG3, 0x0c }, /* No sleep or clear on status read. */
		{ TCS3430_AZ_CONFIG, 0x7f }, /* Autozero at the first cycle. */
		{ TCS3430_PERS, 0 }, /* ALS interrupt at every completed cycle. */
		{ TCS3430_STATUS, TCS3430_AINT | TCS3430_ASAT },
		{ TCS3430_INTENAB, TCS3430_AINT },
		/* Set both bits together to run autozero before measuring. */
		{ TCS3430_ENABLE, TCS3430_PON | TCS3430_AEN },
	};
	int ret, status, i;

	data->needs_config = true;
	for (i = 0; i < ARRAY_SIZE(config); i++) {
		ret = i2c_smbus_write_byte_data(client, config[i][0], config[i][1]);
		if (ret < 0)
			goto power_down;
	}

	/*
	 * There is no data-valid bit. Poll the ALS completion interrupt instead
	 * of assuming that a delay covers oscillator startup and autozero. No
	 * host IRQ is requested; the interrupt output is disabled after this
	 * first conversion. Allow one second for startup plus a full integration.
	 */
	ret = read_poll_timeout(i2c_smbus_read_byte_data, status,
			       status < 0 || (status & TCS3430_AINT), 1000,
			       1000000 + (data->atime + 1) * TCS3430_TIME_STEP_MAX_US,
			       false, client, TCS3430_STATUS);
	if (ret)
		goto power_down;
	if (status < 0) {
		ret = status;
		goto power_down;
	}

	ret = i2c_smbus_write_byte_data(client, TCS3430_INTENAB, 0);
	if (ret < 0)
		goto power_down;
	ret = i2c_smbus_write_byte_data(client, TCS3430_STATUS,
				      TCS3430_AINT | TCS3430_ASAT);
	if (ret < 0)
		goto power_down;

	data->needs_config = false;
	return 0;

power_down:
	i2c_smbus_write_byte_data(client, TCS3430_INTENAB, 0);
	i2c_smbus_write_byte_data(client, TCS3430_ENABLE, 0);
	return ret;
}

static int tcs3430_read_raw(struct iio_dev *indio_dev,
			  const struct iio_chan_spec *chan,
			  int *val, int *val2, long mask)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	struct device *dev = &data->client->dev;
	int ret;

	if (mask == IIO_CHAN_INFO_RAW) {
		ret = pm_runtime_resume_and_get(dev);
		if (ret < 0)
			return ret;

		mutex_lock(&data->lock);
		ret = data->needs_config ? tcs3430_start(data) : 0;
		if (!ret)
			ret = i2c_smbus_read_word_data(data->client, chan->address);
		if (ret >= 0)
			*val = ret;
		mutex_unlock(&data->lock);

		pm_runtime_mark_last_busy(dev);
		pm_runtime_put_autosuspend(dev);
		return ret < 0 ? ret : IIO_VAL_INT;
	}

	guard(mutex)(&data->lock);
	switch (mask) {
	case IIO_CHAN_INFO_HARDWAREGAIN:
		*val = tcs3430_gains[data->gain];
		return IIO_VAL_INT;
	case IIO_CHAN_INFO_INT_TIME:
		*val = 0;
		*val2 = (data->atime + 1) * TCS3430_TIME_STEP_US;
		return IIO_VAL_INT_PLUS_MICRO;
	default:
		return -EINVAL;
	}
}

static int tcs3430_read_avail(struct iio_dev *indio_dev,
			    const struct iio_chan_spec *chan, const int **vals,
			    int *type, int *length, long mask)
{
	switch (mask) {
	case IIO_CHAN_INFO_HARDWAREGAIN:
		*vals = tcs3430_gains;
		*type = IIO_VAL_INT;
		*length = ARRAY_SIZE(tcs3430_gains);
		return IIO_AVAIL_LIST;
	case IIO_CHAN_INFO_INT_TIME:
		*vals = tcs3430_times;
		*type = IIO_VAL_INT_PLUS_MICRO;
		*length = ARRAY_SIZE(tcs3430_times);
		return IIO_AVAIL_RANGE;
	default:
		return -EINVAL;
	}
}

static int tcs3430_write_raw(struct iio_dev *indio_dev,
			   const struct iio_chan_spec *chan,
			   int val, int val2, long mask)
{
	struct tcs3430_data *data = iio_priv(indio_dev);
	int i;

	guard(mutex)(&data->lock);
	switch (mask) {
	case IIO_CHAN_INFO_HARDWAREGAIN:
		if (val2)
			return -EINVAL;
		for (i = 0; i < ARRAY_SIZE(tcs3430_gains); i++) {
			if (val == tcs3430_gains[i]) {
				data->gain = i;
				data->needs_config = true;
				return 0;
			}
		}
		return -EINVAL;
	case IIO_CHAN_INFO_INT_TIME:
		if (val || val2 < TCS3430_TIME_STEP_US ||
		    val2 > 256 * TCS3430_TIME_STEP_US ||
		    val2 % TCS3430_TIME_STEP_US)
			return -EINVAL;
		data->atime = val2 / TCS3430_TIME_STEP_US - 1;
		data->needs_config = true;
		return 0;
	default:
		return -EINVAL;
	}
}

static const struct iio_info tcs3430_info = {
	.read_raw = tcs3430_read_raw,
	.read_avail = tcs3430_read_avail,
	.write_raw = tcs3430_write_raw,
};

static int tcs3430_runtime_suspend(struct device *dev)
{
	struct tcs3430_data *data = iio_priv(dev_get_drvdata(dev));

	guard(mutex)(&data->lock);
	data->needs_config = true;
	return i2c_smbus_write_byte_data(data->client, TCS3430_ENABLE, 0);
}

static int tcs3430_runtime_resume(struct device *dev)
{
	struct tcs3430_data *data = iio_priv(dev_get_drvdata(dev));

	guard(mutex)(&data->lock);
	return tcs3430_start(data);
}

static void tcs3430_power_down(void *arg)
{
	struct tcs3430_data *data = arg;

	i2c_smbus_write_byte_data(data->client, TCS3430_INTENAB, 0);
	i2c_smbus_write_byte_data(data->client, TCS3430_ENABLE, 0);
}

static int tcs3430_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct tcs3430_data *data;
	struct iio_dev *indio_dev;
	int ret;

	if (!i2c_check_functionality(client->adapter,
				     I2C_FUNC_SMBUS_BYTE_DATA | I2C_FUNC_SMBUS_WORD_DATA))
		return -EOPNOTSUPP;

	ret = i2c_smbus_read_byte_data(client, TCS3430_ID);
	if (ret < 0)
		return dev_err_probe(dev, ret, "Cannot read device ID\n");
	if ((ret & TCS3430_ID_MASK) != TCS3430_ID_VALUE)
		return dev_err_probe(dev, -ENODEV, "Unexpected device ID %#x\n", ret);

	indio_dev = devm_iio_device_alloc(dev, sizeof(*data));
	if (!indio_dev)
		return -ENOMEM;

	data = iio_priv(indio_dev);
	data->client = client;
	data->atime = 35; /* 100.08 ms */
	data->gain = 2; /* 16x */
	data->needs_config = true;
	mutex_init(&data->lock);
	i2c_set_clientdata(client, indio_dev);
	indio_dev->name = "tcs3430";
	indio_dev->info = &tcs3430_info;
	indio_dev->modes = INDIO_DIRECT_MODE;
	indio_dev->channels = tcs3430_channels;
	indio_dev->num_channels = ARRAY_SIZE(tcs3430_channels);

	ret = devm_add_action_or_reset(dev, tcs3430_power_down, data);
	if (ret)
		return ret;
	ret = i2c_smbus_write_byte_data(client, TCS3430_INTENAB, 0);
	if (ret < 0)
		return ret;
	ret = i2c_smbus_write_byte_data(client, TCS3430_ENABLE, 0);
	if (ret < 0)
		return ret;
	ret = pm_runtime_set_suspended(dev);
	if (ret)
		return ret;

	pm_runtime_set_autosuspend_delay(dev, 1000);
	pm_runtime_use_autosuspend(dev);
	ret = devm_pm_runtime_enable(dev);
	if (ret)
		return ret;

	return devm_iio_device_register(dev, indio_dev);
}

static const struct dev_pm_ops tcs3430_pm_ops = {
	RUNTIME_PM_OPS(tcs3430_runtime_suspend, tcs3430_runtime_resume, NULL)
	SYSTEM_SLEEP_PM_OPS(pm_runtime_force_suspend, pm_runtime_force_resume)
};

static const struct of_device_id tcs3430_of_match[] = {
	{ .compatible = "ams,tcs3430" },
	{ }
};
MODULE_DEVICE_TABLE(of, tcs3430_of_match);

static const struct i2c_device_id tcs3430_id[] = {
	{ "tcs3430" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, tcs3430_id);

static struct i2c_driver tcs3430_driver = {
	.driver = {
		.name = "tcs3430",
		.of_match_table = tcs3430_of_match,
		.pm = pm_ptr(&tcs3430_pm_ops),
	},
	.probe = tcs3430_probe,
	.id_table = tcs3430_id,
};
module_i2c_driver(tcs3430_driver);

MODULE_DESCRIPTION("AMS TCS3430 color and infrared sensor");
MODULE_LICENSE("GPL");
