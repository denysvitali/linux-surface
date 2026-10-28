/* SPDX-License-Identifier: GPL-2.0 */
/* Surface Pro X module actuator, powered only with the OV13858 stream. */
#ifndef OV13858_FOCUS_H
#define OV13858_FOCUS_H

struct ov13858_focus {
	struct i2c_client *client;
	u8 saved[5];
	bool saved_valid;
	bool active;
	int last_position;
};

static int ov13858_focus_read_bytes(struct ov13858_focus *focus, u8 reg,
				    u8 *value, unsigned int length)
{
	struct i2c_msg msgs[] = {
		{ .addr = focus->client->addr, .len = 1, .buf = &reg },
		{ .addr = focus->client->addr, .flags = I2C_M_RD,
		  .len = length, .buf = value },
	};
	int ret = i2c_transfer(focus->client->adapter, msgs, 2);

	return ret == 2 ? 0 : ret < 0 ? ret : -EIO;
}

static int ov13858_focus_read(struct ov13858_focus *focus, u8 reg, u8 *value)
{
	return ov13858_focus_read_bytes(focus, reg, value, 1);
}

static int ov13858_focus_position(struct ov13858_focus *focus, int *position)
{
	u8 buf[2];
	int ret = ov13858_focus_read_bytes(focus, 3, buf, 2);

	if (!ret)
		*position = ((buf[0] & 3) << 8) | buf[1];
	return ret;
}

static int ov13858_focus_write(struct ov13858_focus *focus, u8 reg, u8 value)
{
	u8 buf[] = { reg, value };
	int ret = i2c_master_send(focus->client, buf, sizeof(buf));

	return ret == sizeof(buf) ? 0 : ret < 0 ? ret : -EIO;
}

static int ov13858_focus_move(struct ov13858_focus *focus, int target)
{
	int pos, next, ret, i;

	ret = ov13858_focus_position(focus, &pos);
	if (ret)
		return ret;
	while (pos != target) {
		u8 buf[3];

		next = pos + clamp(target - pos, -16, 16);
		buf[0] = 3;
		buf[1] = next >> 8;
		buf[2] = next & 0xff;
		ret = i2c_master_send(focus->client, buf, sizeof(buf));
		if (ret != sizeof(buf))
			return ret < 0 ? ret : -EIO;
		/* Allow SAC to finish before sending the next bounded step. */
		for (i = 0; i < 20; i++) {
			usleep_range(10000, 11000);
			ret = ov13858_focus_position(focus, &pos);
			focus->last_position = ret ? -1 : pos;
			if (ret)
				return ret;
			if (pos == next)
				break;
		}
		if (pos != next)
			return -EIO;
	}
	return 0;
}

static int ov13858_focus_restore(struct ov13858_focus *focus)
{
	static const u8 regs[] = { 2, 3, 4, 6, 7 };
	int ret = 0, err, i;
	u8 value;

	focus->active = false;
	if (!focus->saved_valid)
		return 0;

	/* Restore position while configured, then timing, mode and control. */
	err = ov13858_focus_move(focus, ((focus->saved[1] & 3) << 8) |
					 focus->saved[2]);
	if (err)
		ret = err;
	for (i = 4; i >= 0; i--) {
		if (i == 1 || i == 2)
			continue;
		err = ov13858_focus_write(focus, regs[i], focus->saved[i]);
		if (err && !ret)
			ret = err;
	}
	/* Check every saved register, including position. */
	for (i = 0; i < ARRAY_SIZE(regs); i++) {
		if (i == 2)
			continue;
		if (i == 1) {
			u8 position[2];

			err = ov13858_focus_read_bytes(focus, 3, position, 2);
			if (!err && (position[0] != focus->saved[1] ||
				     position[1] != focus->saved[2]))
				err = -EIO;
			if (err && !ret)
				ret = err;
			continue;
		}
		err = ov13858_focus_read(focus, regs[i], &value);
		if (!err && value != focus->saved[i])
			err = -EIO;
		if (err && !ret)
			ret = err;
	}
	if (!ret)
		focus->saved_valid = false;
	return ret;
}

static int ov13858_focus_start(struct ov13858_focus *focus, int position)
{
	static const u8 regs[] = { 2, 3, 4, 6, 7 };
	u8 id;
	int ret, err, i;

	if (focus->saved_valid)
		return -EIO;
	ret = ov13858_focus_read(focus, 0, &id);
	if (ret)
		return ret;
	if (id != 0xf2)
		return -ENODEV;
	for (i = 0; i < ARRAY_SIZE(regs); i++) {
		if (i == 2)
			continue;
		ret = ov13858_focus_read_bytes(focus, regs[i], &focus->saved[i],
					      i == 1 ? 2 : 1);
		if (ret)
			return ret;
	}
	focus->saved_valid = true;
	ret = ov13858_focus_write(focus, 2, 2);
	if (!ret)
		ret = ov13858_focus_write(focus, 6, 0x40);
	if (!ret)
		ret = ov13858_focus_write(focus, 7, 0x53);
	if (!ret)
		ret = ov13858_focus_move(focus, position);
	if (ret) {
		err = ov13858_focus_restore(focus);
		return err ? err : ret;
	}
	focus->active = true;
	return 0;
}
#endif
