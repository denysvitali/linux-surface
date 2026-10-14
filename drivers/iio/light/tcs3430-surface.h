/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _TCS3430_SURFACE_H
#define _TCS3430_SURFACE_H

#include "tcs3430-surface-calib.h"

/* Channels are Q24, returned lux Q16; calibration coefficients Q24/Q32. */
#define TCS3430_COUNT_ONE (1LL << 24)
#define TCS3430_COEFF_ONE (1LL << 24)

/* Split before multiplication: normalized counts * matrix can exceed s64. */
static s64 tcs3430_mul_coeff(s64 count, s64 coeff)
{
	return div64_s64(count, TCS3430_COEFF_ONE) * coeff +
		div64_s64((count % TCS3430_COEFF_ONE) * coeff,
			  TCS3430_COEFF_ONE);
}

static s64 tcs3430_mul_q32(s64 count, s64 coeff)
{
	return div64_s64(div64_s64(count, TCS3430_COUNT_ONE) * coeff, 256) +
		div64_s64((count % TCS3430_COUNT_ONE) * coeff, 1LL << 32);
}

/* Binary32 classifier inputs: round to 24 significant bits, ties to even. */
static s64 tcs3430_classifier_count(s64 count)
{
	int shift = fls64(count) - 24;
	s64 half, rounded;

	if (shift <= 0)
		return count;
	half = 1LL << (shift - 1);
	rounded = (count + half - 1 + ((count >> shift) & 1)) >> shift;
	return rounded << shift;
}

static s64 tcs3430_correct_count(u16 n, int channel)
{
	s64 factor;
	int i;

	/* This unusual dark-count value is specified by the Windows routine. */
	if (!n)
		return TCS3430_COUNT_ONE;
	for (i = 0; i < 15 && n >= tcs3430_knots[i + 1]; i++)
		;
	factor = tcs3430_nonlinear[i][channel];
	if (i < 15)
		factor += div64_s64((tcs3430_nonlinear[i + 1][channel] - factor) *
				    (n - tcs3430_knots[i]),
				    tcs3430_knots[i + 1] - tcs3430_knots[i]);
	return n * factor;
}

/*
 * Conversion from SurfaceLightSensor.sys 1.37.139.0, using this unit's Type_3.
 * Caller serializes saved[] per device; initialize it to {35, 45, 6, 0}.
 * Preserve it across gain/time changes and runtime PM, as Windows does.
 * Return -ERANGE instead of Windows HID's held-last-report policy on rejection.
 * ATIME=0 remains available for raw reads but Windows rejects its conversion.
 * class_out is also used by the offline host comparison of this exact code.
 */
static int tcs3430_surface_lux(const u16 raw[4], u8 atime, u8 gain,
			       u32 saved[4], s64 *lux, int *class_out)
{
	s64 corrected[4], normalized[4], xyz[3] = {};
	s64 high, low, n, fy, fx, a, b, score, best = 0, scale, cx, cy, cir;
	s64 base_a = tcs3430_class_target[0][0];
	s64 base_b = tcs3430_class_target[0][1];
	s64 x, y, wa, wb, wc, den, xr, yr, xg, yg, xb, yb;
	u16 r[4];
	u32 sum = 0, saved_sum = 0;
	int i, j, k, selected = 1;

	*class_out = 0;
	if (!atime || gain > 3)
		return -ERANGE;
	scale = div64_s64(tcs3430_exposure * TCS3430_COEFF_ONE,
			  (s64)tcs3430_effective_gain[gain] * (atime + 1));
	for (j = 0; j < 4; j++) {
		if (raw[j] == 65535)
			return -ERANGE;
		r[j] = raw[j];
		sum += r[j];
		saved_sum += saved[j];
	}
	if (!gain) {
		saved[0] = 35;
		saved[1] = 45;
		saved[2] = 6;
		saved[3] = 0;
	} else if (sum < 80) {
		if (!saved_sum)
			return -ERANGE;
		for (j = 0; j < 4; j++)
			r[j] = sum * saved[j] / saved_sum;
	} else {
		for (j = 0; j < 4; j++)
			saved[j] = r[j];
	}
	for (j = 0; j < 4; j++) {
		n = tcs3430_correct_count(r[j], j);
		high = tcs3430_mul_q32(n, tcs3430_reference_ratio[0][j]);
		low = tcs3430_mul_q32(n, tcs3430_reference_ratio[1][j]);
		if (r[1] > tcs3430_reference_y[0])
			corrected[j] = high;
		else if (r[1] < tcs3430_reference_y[1])
			corrected[j] = low;
		else
			corrected[j] = high + div64_s64((low - high) *
				(tcs3430_reference_y[0] - r[1]),
				tcs3430_reference_y[0] - tcs3430_reference_y[1]);
		normalized[j] = tcs3430_mul_q32(corrected[j], scale);
	}
	if (r[2] && corrected[3] > 100 * corrected[2])
		return -ERANGE;
	cx = tcs3430_classifier_count(corrected[0]);
	cy = tcs3430_classifier_count(corrected[1]);
	cir = tcs3430_classifier_count(corrected[3]);
	if (cir > 50 * TCS3430_COUNT_ONE && cir > 8 * cy) {
		selected = 0;
	} else {
		/*
		 * All four nearest-reference records use normalized Y and X/Y.
		 * Q24 affine distance relative to the first target omits the
		 * common feature norm and sqrt, avoiding large squared values.
		 * With u16 counts, ATIME>=1 and these coefficients, all products
		 * fit s64. Ties keep the first class, just like Windows.
		 */
		fy = tcs3430_mul_q32(cy, scale);
		fx = div64_s64(cx * (1LL << 20), cy) * 16;
		for (i = 0; i < 4; i++) {
			a = tcs3430_class_target[i][0];
			b = tcs3430_class_target[i][1];
			score = div64_s64(a * a + b * b - base_a * base_a -
					 base_b * base_b, TCS3430_COEFF_ONE) -
				2 * (tcs3430_mul_coeff(fy, a - base_a) +
				     tcs3430_mul_coeff(fx, b - base_b));
			if (!i || score < best) {
				best = score;
				selected = i + 1;
			}
		}
	}
	*class_out = selected + 1;
	for (k = 0; k < 3; k++)
		for (j = 0; j < 4; j++)
			xyz[k] += tcs3430_mul_coeff(normalized[j],
						   tcs3430_matrix[selected][k][j]);
	if (xyz[1] > 200000 * TCS3430_COUNT_ONE)
		return -ERANGE;

	/* Windows RGB-triangle validity check; chromaticity coordinates Q20. */
	x = div64_s64(xyz[0] * (1LL << 20), xyz[0] + xyz[1] + xyz[2]);
	y = div64_s64(xyz[1] * (1LL << 20), xyz[0] + xyz[1] + xyz[2]);
	xr = tcs3430_triangle[0] / 16;
	yr = tcs3430_triangle[1] / 16;
	xg = tcs3430_triangle[2] / 16;
	yg = tcs3430_triangle[3] / 16;
	xb = tcs3430_triangle[4] / 16;
	yb = tcs3430_triangle[5] / 16;
	den = (yg - yb) * (xr - xb) - (xg - xb) * (yr - yb);
	wa = (yg - yb) * (x - xb) - (xg - xb) * (y - yb);
	wb = (xr - xb) * (y - yb) - (yr - yb) * (x - xb);
	wc = den - wa - wb;
	if (wa <= 0 || wa >= den || wb <= 0 || wb >= den ||
	    wc <= 0 || wc >= den)
		return -ERANGE;
	*lux = xyz[1] >> 8;
	return 0;
}

#endif /* _TCS3430_SURFACE_H */
