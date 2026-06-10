#!/bin/bash
# Dual screen rotation for Lenovo Yoga Book 9 14IAH10
# Reads the bottom screen accelerometer and rotates both displays together.
# Detects tent mode by comparing both accelerometers and mirrors displays.
# Runs as a system service (/etc/systemd/system/screen-rotate.service).

find_accels() {
    local first=""
    local second=""
    for dev in /sys/bus/iio/devices/iio:device*; do
        name=$(cat "$dev/name" 2>/dev/null)
        if [ "$name" = "accel_3d" ]; then
            y=$(cat "$dev/in_accel_y_raw" 2>/dev/null)
            if [ -n "$y" ]; then
                if [ -z "$first" ]; then
                    first="$dev"
                else
                    second="$dev"
                    break
                fi
            fi
        fi
    done
    echo "$first $second"
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

read -r ACCEL ACCEL2 <<< "$(find_accels)"

if [ -z "$ACCEL" ] || [ -z "$ACCEL2" ]; then
    echo "ERROR: Could not find both accelerometer devices"
    exit 1
fi

echo "Using accelerometers: $ACCEL and $ACCEL2"

# kbdock sysfs attribute: non-zero means keyboard is physically docked.
# When docked the device is used as a laptop; accelerometer rotation is locked
# to normal so that sudden movements don't cause spurious screen rotations.
KBDOCK_SYSFS=$(ls /sys/bus/wmi/devices/806BD2A2-177B-481D-BFB5-3BA0BB4A2285-*/keyboard_position 2>/dev/null | head -1)
if [ -z "$KBDOCK_SYSFS" ]; then
    echo "WARNING: kbdock sysfs not found; rotation will not be suppressed while keyboard is docked"
fi

PREV=""
PENDING_ORI=""
PENDING_COUNT=0
DEBOUNCE_COUNT=3  # consecutive same-orientation readings required before rotating
ROTATE_THRESHOLD=3  # minimum normalized accel units to leave current orientation (tune up to increase dead zone)

while true; do
    # While the keyboard is docked, lock rotation to normal (laptop orientation)
    # and skip the accelerometer entirely.  This prevents transient accel spikes
    # during movement from briefly rotating the display.
    if [ -n "$KBDOCK_SYSFS" ]; then
        dock_pos=$(cat "$KBDOCK_SYSFS" 2>/dev/null)
        if [ "${dock_pos:-0}" != "0" ]; then
            if [ "normal" != "$PREV" ]; then
                echo "Rotating to: normal (keyboard docked, pos=$dock_pos)"
                apply_rotation \
                    output.eDP-1.rotation.inverted \
                    output.eDP-1.position.0,0 \
                    output.eDP-2.rotation.none \
                    output.eDP-2.position.0,1125
                PREV="normal"
            fi
            sleep 1
            continue
        fi
    fi

    X=$(cat "$ACCEL/in_accel_x_raw" 2>/dev/null)
    Y=$(cat "$ACCEL/in_accel_y_raw" 2>/dev/null)
    Y2=$(cat "$ACCEL2/in_accel_y_raw" 2>/dev/null)

    # Normalize to ~1000 range regardless of driver scale
    X=$((X / 1000))
    Y=$((Y / 1000))
    Y2=$((Y2 / 1000))

    AX=${X#-}
    AY=${Y#-}

    # Tent mode: both accelerometers have opposite Y signs
    if ( [ "$Y" -lt "0" ] && [ "$Y2" -gt "0" ] ) || \
       ( [ "$Y" -gt "0" ] && [ "$Y2" -lt "0" ] ); then
        ORI="tent"
    elif [ "$AY" -gt "$AX" ]; then
        # Portrait: require Y to exceed ROTATE_THRESHOLD to avoid rotating at
        # slight tilts (e.g. resting in lap at a small angle).
        if [ "$Y" -lt "-$ROTATE_THRESHOLD" ]; then
            ORI="normal"
        elif [ "$Y" -gt "$ROTATE_THRESHOLD" ]; then
            ORI="inverted"
        else
            ORI="${PREV:-normal}"  # dead zone — hold current orientation
        fi
    else
        if [ "$X" -lt "-$ROTATE_THRESHOLD" ]; then
            ORI="right"
        elif [ "$X" -gt "$ROTATE_THRESHOLD" ]; then
            ORI="left"
        else
            ORI="${PREV:-normal}"
        fi
    fi

    if [ "$ORI" = "$PREV" ]; then
        PENDING_ORI=""
        PENDING_COUNT=0
    else
        if [ "$ORI" = "$PENDING_ORI" ]; then
            PENDING_COUNT=$((PENDING_COUNT + 1))
        else
            PENDING_ORI="$ORI"
            PENDING_COUNT=1
        fi

        if [ "$PENDING_COUNT" -ge "$DEBOUNCE_COUNT" ]; then
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
                tent)
                    apply_rotation \
                        output.eDP-1.rotation.none \
                        output.eDP-1.position.0,0 \
                        output.eDP-2.rotation.none \
                        output.eDP-2.position.0,0 ;;
            esac
            PREV=$ORI
            PENDING_ORI=""
            PENDING_COUNT=0
        fi
    fi

    sleep 1
done
