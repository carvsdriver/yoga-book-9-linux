#!/bin/bash
# Dynamically find the bottom screen accelerometer
# We identify it by testing which accel_3d device reports
# correct gravity values in normal laptop orientation

find_accel() {
    for dev in /sys/bus/iio/devices/iio:device*; do
        name=$(cat "$dev/name" 2>/dev/null)
        if [ "$name" = "accel_3d" ]; then
            # Check if this device has readable data
            y=$(cat "$dev/in_accel_y_raw" 2>/dev/null)
            if [ -n "$y" ]; then
                echo "$dev"
                return
            fi
        fi
    done
}

ACCEL=$(find_accel)

if [ -z "$ACCEL" ]; then
    echo "ERROR: Could not find accelerometer device"
    exit 1
fi

echo "Using accelerometer: $ACCEL"

PREV=""

while true; do
    X=$(cat "$ACCEL/in_accel_x_raw" 2>/dev/null)
    Y=$(cat "$ACCEL/in_accel_y_raw" 2>/dev/null)

    AX=${X#-}
    AY=${Y#-}

    if [ "$AY" -gt "$AX" ]; then
        [ "$Y" -lt "0" ] && ORI="normal" || ORI="inverted"
    else
        [ "$X" -lt "0" ] && ORI="right" || ORI="left"
    fi

    if [ "$ORI" != "$PREV" ]; then
        echo "Rotating to: $ORI"
        case $ORI in
            normal)
                kscreen-doctor \
                    output.eDP-1.rotation.inverted \
                    output.eDP-1.position.0,0 \
                    output.eDP-2.rotation.none \
                    output.eDP-2.position.0,1125 ;;
            inverted)
                kscreen-doctor \
                    output.eDP-1.rotation.none \
                    output.eDP-1.position.0,1125 \
                    output.eDP-2.rotation.inverted \
                    output.eDP-2.position.0,0 ;;
            right)
                kscreen-doctor \
                    output.eDP-1.rotation.left \
                    output.eDP-1.position.0,0 \
                    output.eDP-2.rotation.right \
                    output.eDP-2.position.1125,0 ;;
            left)
                kscreen-doctor \
                    output.eDP-1.rotation.right \
                    output.eDP-1.position.1125,0 \
                    output.eDP-2.rotation.left \
                    output.eDP-2.position.0,0 ;;
        esac
        PREV=$ORI
    fi

    sleep 1
done
