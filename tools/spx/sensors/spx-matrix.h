/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SPX_MATRIX_H
#define SPX_MATRIX_H

#include <math.h>
#include <stdbool.h>
#include <string.h>

/* Validate the existing libssc 3x3 interpretation. Do not infer board axes.
 * Both handednesses are accepted: signed axis mappings may be reflections.
 * A small tolerance accommodates single-precision rotation coefficients.
 */
static inline bool spx_matrix_sanitize(float matrix[3][3], bool complete)
{
    const float tolerance = 0.001f;
    bool valid = complete;
    for (unsigned row = 0; row < 3; row++) {
        for (unsigned column = 0; column < 3; column++)
            if (!isfinite(matrix[row][column]))
                valid = false;
        for (unsigned other = 0; other <= row; other++) {
            float dot = 0;
            for (unsigned column = 0; column < 3; column++)
                dot += matrix[row][column] * matrix[other][column];
            if (!isfinite(dot) || fabsf(dot - (row == other ? 1.0f : 0.0f)) > tolerance)
                valid = false;
        }
    }
    if (!valid) {
        /* Explicit compatibility fallback; it does not verify physical axes. */
        memset(matrix, 0, 9 * sizeof(float));
        for (unsigned axis = 0; axis < 3; axis++)
            matrix[axis][axis] = 1.0f;
    }
    return valid;
}

#endif
