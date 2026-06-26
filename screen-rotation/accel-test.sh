#!/bin/bash
# Logs both accelerometer raw values + corrected values every second, timestamped.
# Run for ~90 seconds while cycling through test positions.
OUTFILE="/tmp/accel-test-$(date +%s).log"
echo "Logging to $OUTFILE"
echo "START $(date)" >> "$OUTFILE"
for i in $(seq 1 90); do
    ts=$(date +%H:%M:%S)
    x2=$(cat /sys/bus/iio/devices/iio:device2/in_accel_x_raw)
    y2=$(cat /sys/bus/iio/devices/iio:device2/in_accel_y_raw)
    z2=$(cat /sys/bus/iio/devices/iio:device2/in_accel_z_raw)
    x3=$(cat /sys/bus/iio/devices/iio:device3/in_accel_x_raw)
    y3=$(cat /sys/bus/iio/devices/iio:device3/in_accel_y_raw)
    z3=$(cat /sys/bus/iio/devices/iio:device3/in_accel_z_raw)
    cx2=$((-x2/1000)); cy2=$((-y2/1000)); cz2=$((z2/1000))
    cx3=$((-x3/1000)); cy3=$((-y3/1000)); cz3=$((z3/1000))
    echo "$ts raw2=[$((x2/1000)),$((y2/1000)),$((z2/1000))] corr2=[$cx2,$cy2,$cz2]  raw3=[$((x3/1000)),$((y3/1000)),$((z3/1000))] corr3=[$cx3,$cy3,$cz3]" | tee -a "$OUTFILE"
    sleep 1
done
echo "END $(date)" >> "$OUTFILE"
echo "Log saved: $OUTFILE"
