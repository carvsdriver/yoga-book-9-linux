#!/bin/bash
# Dual screen rotation for Lenovo Yoga Book 9 14IAH10
# Reads the bottom screen accelerometer and rotates both displays together.
# Runs as a system service (/etc/systemd/system/screen-rotate.service).

find_accel() {
    for dev in /sys/bus/iio/devices/iio:device*; do
        name=$(cat "$dev/name" 2>/dev/null)
        if [ "$name" = "accel_3d" ]; then
            y=$(cat "$dev/in_accel_y_raw" 2>/dev/null)
            if [ -n "$y" ]; then
                echo "$dev"
                return
            fi
        fi
    done
}

apply_rotation() {
    for i in 1 2 3 4 5; do
        kscreen-doctor "$@" 2>&1 && return 0
        echo "kscreen-doctor failed, retry $i..."
        sleep 2
    done
    echo "kscreen-doctor failed after 5 attempts"
    return 1
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

    # Normalize to ~1000 range regardless of driver scale
    X=$((X / 1000))
    Y=$((Y / 1000))

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
                apply_rotation \
                    output.eDP-1.rotation.inverted \
                    output.eDP-1.position.0,0 \
                    output.eDP-2.rotation.none \
                    output.eDP-2.position.0,1125 ;;
            inverted)
                apply_rotation \
                    output.eDP-1.rotation.none \
                    output.eDP-1.position.0,1125 \
                    output.eDP-2.rotation.inverted \
                    output.eDP-2.position.0,0 ;;
            right)
                apply_rotation \
                    output.eDP-1.rotation.left \
                    output.eDP-1.position.0,0 \
                    output.eDP-2.rotation.right \
                    output.eDP-2.position.1125,0 ;;
            left)
                apply_rotation \
                    output.eDP-1.rotation.right \
                    output.eDP-1.position.1125,0 \
                    output.eDP-2.rotation.left \
                    output.eDP-2.position.0,0 ;;
        esac
        PREV=$ORI
    fi

    sleep 1
done
