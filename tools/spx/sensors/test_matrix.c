/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "spx-matrix.h"
#include <assert.h>
#include <stdio.h>

static void valid_unchanged(float matrix[3][3])
{
    float original[3][3];
    memcpy(original, matrix, sizeof(original));
    assert(spx_matrix_sanitize(matrix, true));
    assert(memcmp(original, matrix, sizeof(original)) == 0);
}

static void fallback(float matrix[3][3], bool complete)
{
    assert(!spx_matrix_sanitize(matrix, complete));
    for (unsigned row = 0; row < 3; row++)
        for (unsigned column = 0; column < 3; column++)
            assert(matrix[row][column] == (row == column ? 1.0f : 0.0f));
}

int main(void)
{
    float fractional_degenerate[3][3] = {{.1f, .1f, .1f}, {0}, {0}};
    float old_fallback_residue[3][3] = {{1, .1f, .1f}, {0, 1, 0}, {0, 0, 1}};
    float zero[3][3] = {{0}};
    float nan_matrix[3][3] = {{1, NAN, 0}, {0, 1, 0}, {0, 0, 1}};
    float inf_matrix[3][3] = {{1, 0, 0}, {INFINITY, 1, 0}, {0, 0, 1}};
    float cancellation[3][3] = {{.5f, .5f, -.7071067812f},
                              {.5f, .5f, .7071067812f},
                              {.7071067812f, -.7071067812f, 0}};
    float fractional_rotation[3][3] = {{.7071067812f, -.7071067812f, 0},
                                     {.7071067812f, .7071067812f, 0}, {0, 0, 1}};
    /* Orthonormal 90-degree rotation about (1,-1,0), signed sum zero. */
    float signed_sum_zero[3][3] = {{.5f, -.5f, -.7071067812f},
                                 {-.5f, .5f, -.7071067812f},
                                 {.7071067812f, .7071067812f, 0}};
    float rotation[3][3] = {{0, -1, 0}, {1, 0, 0}, {0, 0, 1}};
    float incomplete[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
    fallback(fractional_degenerate, true);
    fallback(old_fallback_residue, true);
    fallback(zero, true);
    fallback(nan_matrix, true);
    fallback(inf_matrix, true);
    fallback(incomplete, false);
    valid_unchanged(cancellation);
    valid_unchanged(fractional_rotation);
    valid_unchanged(signed_sum_zero);
    valid_unchanged(rotation);
    puts("matrix validation: all offline cases passed");
    return 0;
}
