/* SPDX-License-Identifier: GPL-2.0-only */
/* Metadata readiness only: do not enable a stream or claim desktop policy. */
#include <libssc-sensor-accelerometer.h>
#include <stdio.h>

int main(void)
{
    GError *error = NULL;
    SSCSensorAccelerometer *sensor = ssc_sensor_accelerometer_new_sync(NULL, &error);
    gboolean ready;
    guint64 low = 0, high = 0;
    gchar *name = NULL, *data_type = NULL;

    if (!sensor) {
        fprintf(stderr, "SSC accelerometer unavailable: %s\n", error ? error->message : "no object");
        g_clear_error(&error);
        return 1;
    }
    g_object_get(sensor, SSC_SENSOR_DATA_TYPE, &data_type,
                 SSC_SENSOR_UID_LOW, &low, SSC_SENSOR_UID_HIGH, &high,
                 SSC_SENSOR_NAME, &name, NULL);
    ready = (low || high) && name && g_strcmp0(data_type, "accel") == 0;
    if (ready)
        printf("SSC accelerometer ready: %s (%016" G_GINT64_MODIFIER "x%016" G_GINT64_MODIFIER "x)\n",
               name ? name : "unnamed", high, low);
    g_free(name);
    g_free(data_type);
    g_object_unref(sensor);
    return ready ? 0 : 1;
}
