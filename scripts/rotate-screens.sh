#!/bin/bash
# rotate-screens.sh
# Reads the bottom screen accelerometer (iio:device0) and rotates
# both displays together on the Lenovo Yoga Book 9i.
#
# Installed as a systemd user service - see screen-rotate.service

PREV=""

while true; do
    X=$(cat /sys/bus/iio/devices/iio:device0/in_accel_x_raw)
    Y=$(cat /sys/bus/iio/devices/iio:device0/in_accel_y_raw)

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
                kscreen-doctor output.eDP-1.rotation.inverted output.eDP-2.rotation.none ;;
            inverted)
                kscreen-doctor output.eDP-1.rotation.none output.eDP-2.rotation.inverted ;;
            right)
                kscreen-doctor output.eDP-1.rotation.left output.eDP-2.rotation.right ;;
            left)
                kscreen-doctor output.eDP-1.rotation.right output.eDP-2.rotation.left ;;
        esac
        PREV=$ORI
    fi

    sleep 1
done
