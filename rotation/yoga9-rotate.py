#!/usr/bin/env python3
"""
yoga9-rotate: Dual-screen rotation daemon for Lenovo Yoga Book 9 14IAH10 (83KJ).

Subscribes to net.hadess.SensorProxy (standard, unpatched) for orientation
and reads both accelerometers directly from sysfs for tent mode detection.
Drives synchronized kscreen-doctor rotation for eDP-1 (top) and eDP-2 (bottom).
"""

import glob
import logging
import os
import subprocess
import sys

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

SENSOR_PROXY_BUS = "net.hadess.SensorProxy"
SENSOR_PROXY_PATH = "/net/hadess/SensorProxy"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

# Debounce window before applying a rotation change.
# iio-sensor-proxy's orientation_calc already has 35°+5° hysteresis, so 500ms
# (= 5 hardware samples at 10Hz) absorbs transition noise without feeling slow.
DEBOUNCE_MS = 500

# Tent-mode polling interval: matches hardware delivery rate (10Hz = 100ms).
TENT_POLL_MS = 100

# Raw Y-axis threshold (≈0.1G) for tent mode.  Both accels must exceed this
# with opposite signs.  Prevents false positives when the device is near-flat
# (Y values near zero for both accels).
TENT_Y_THRESHOLD = 100000

# WMI sysfs for the keyboard dock driver.  Absent if driver not loaded.
KBDOCK_GLOB = (
    "/sys/bus/wmi/devices/"
    "E7F300FA-21CD-4003-ADAC-2696135982E6-*/"
    "keyboard_position"
)

# Common path fragment for both accelerometers.  We do not hardcode the HID
# collection index (the number between the last two dots) because the kernel
# renumbers those across versions.  find_accel_paths() sorts by realpath so the
# lower-indexed collection (display/top screen) comes first consistently.
ACCEL_HID_PREFIX = "HID-SENSOR-200073."

# Maps orientation state names to (eDP-1 rotation, position), (eDP-2 rotation, position).
# eDP-1 is physically mounted upside-down so every rotation is the mirror of eDP-2.
# Positions in logical pixels at 1.6x scale: 2880/1.6 = 1800×1125 per screen.
ROTATIONS = {
    #            eDP-1 (top, inverted mount)      eDP-2 (bottom, normal mount)
    "normal":    [("inverted", (0, 0)),           ("none",     (0, 1125))],
    "bottom-up": [("none",     (0, 1125)),        ("inverted", (0, 0))   ],
    # iio "left-up"  = corrected_x > 0 = raw_x < 0 = right edge physically up
    # iio "right-up" = corrected_x < 0 = raw_x > 0 = left  edge physically up
    "left-up":   [("left",     (0, 0)),           ("right",    (1125, 0))],
    "right-up":  [("right",    (1125, 0)),        ("left",     (0, 0))   ],
    # Tent: both screens at (0,0) so compositor can mirror/extend as configured.
    "tent":      [("none",     (0, 0)),           ("none",     (0, 0))   ],
}

log = logging.getLogger("yoga9-rotate")


def find_accel_y_paths():
    """Return (display_y, base_y) in_accel_y_raw paths for the two HID accels.

    Sorted by realpath so the lower HID collection index (display/top screen)
    is always first regardless of kernel-assigned numbering.
    """
    matches = []
    for dev in sorted(glob.glob("/sys/bus/iio/devices/iio:device*")):
        try:
            if open(os.path.join(dev, "name")).read().strip() != "accel_3d":
                continue
        except OSError:
            continue
        rp = os.path.realpath(dev)
        if ACCEL_HID_PREFIX not in rp:
            continue
        y_path = os.path.join(dev, "in_accel_y_raw")
        if os.path.exists(y_path):
            matches.append((rp, y_path))
    matches.sort()
    paths = [y for _, y in matches]
    return (paths[0] if len(paths) > 0 else None,
            paths[1] if len(paths) > 1 else None)


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read())
    except (OSError, ValueError):
        return None


def kbdock_active():
    paths = glob.glob(KBDOCK_GLOB)
    if not paths:
        return False
    try:
        return open(paths[0]).read().strip() != "0"
    except OSError:
        return False


def apply_rotation(state):
    table = ROTATIONS.get(state)
    if table is None:
        log.warning("Unknown orientation state: %r — ignoring", state)
        return
    outputs = ["eDP-1", "eDP-2"]
    args = ["kscreen-doctor"]
    for output, (rotation, (x, y)) in zip(outputs, table):
        args += [
            f"output.{output}.rotation.{rotation}",
            f"output.{output}.position.{x},{y}",
        ]
    log.info("state=%s  %s", state, "  ".join(args[1:]))
    try:
        subprocess.run(args, check=True, timeout=15)
    except subprocess.CalledProcessError as e:
        log.error("kscreen-doctor failed (exit %d)", e.returncode)
    except subprocess.TimeoutExpired:
        log.error("kscreen-doctor timed out")


class RotationDaemon:
    def __init__(self, bus):
        self.bus = bus
        self.orientation = "undefined"
        self.tent_mode = False
        self._debounce_id = None
        self._pending_state = None
        self._display_y = None
        self._base_y = None

    # ------------------------------------------------------------------
    # Tent mode — sysfs polling, no iio-sensor-proxy patch required

    def _find_accel_paths(self):
        self._display_y, self._base_y = find_accel_y_paths()
        if self._display_y and self._base_y:
            log.info("Tent mode enabled: display_y=%s  base_y=%s",
                     self._display_y, self._base_y)
        else:
            log.warning(
                "Cannot find both accel sysfs paths — tent mode disabled "
                "(display=%s, base=%s)", self._display_y, self._base_y
            )

    def _poll_tent(self):
        if not self._display_y or not self._base_y:
            return True  # keep timer; paths may appear after a hotplug

        y_display = read_int(self._display_y)
        y_base    = read_int(self._base_y)
        if y_display is None or y_base is None:
            return True

        # Mount matrix negates X only, so corrected_y == raw_y for both accels.
        tent = (
            abs(y_display) > TENT_Y_THRESHOLD and
            abs(y_base)    > TENT_Y_THRESHOLD and
            (y_display > 0) != (y_base > 0)
        )
        if tent != self.tent_mode:
            self.tent_mode = tent
            log.debug("TentMode → %s", tent)
            self._schedule(self._effective_state())
        return True  # repeat

    # ------------------------------------------------------------------
    # State machine

    def _effective_state(self):
        if self.tent_mode:
            return "tent"
        o = self.orientation
        # The display accelerometer is physically inverted (mounted upside-down
        # in the top screen lid).  iio-sensor-proxy reports "bottom-up" when the
        # device is upright (normal use) and "normal" when it is inverted.
        # Swap those two labels so the ROTATIONS table and kbdock override remain
        # semantically correct.
        if o == "normal":
            o = "bottom-up"
        elif o == "bottom-up":
            o = "normal"
        return o if o in ROTATIONS else "normal"

    def _schedule(self, state):
        self._pending_state = state
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(DEBOUNCE_MS, self._fire)

    def _fire(self):
        self._debounce_id = None
        state = self._pending_state
        self._pending_state = None
        if kbdock_active():
            log.info("Keyboard docked — overriding %r with normal", state)
            state = "normal"
        apply_rotation(state)
        return False

    def _rotate_now(self, state):
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        self._pending_state = None
        apply_rotation(state)

    # ------------------------------------------------------------------
    # D-Bus

    def on_properties_changed(self, iface, changed, _invalidated):
        if iface != SENSOR_PROXY_BUS:
            return
        if "AccelerometerOrientation" in changed:
            self.orientation = str(changed["AccelerometerOrientation"])
            log.debug("AccelerometerOrientation → %s", self.orientation)
            self._schedule(self._effective_state())

    def connect(self):
        try:
            obj = self.bus.get_object(SENSOR_PROXY_BUS, SENSOR_PROXY_PATH)
        except dbus.DBusException as e:
            log.error("Cannot reach iio-sensor-proxy: %s", e)
            return False

        props_iface = dbus.Interface(obj, DBUS_PROPERTIES_IFACE)
        sensor_iface = dbus.Interface(obj, SENSOR_PROXY_BUS)

        self.bus.add_signal_receiver(
            self.on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface=DBUS_PROPERTIES_IFACE,
            bus_name=SENSOR_PROXY_BUS,
            path=SENSOR_PROXY_PATH,
        )

        try:
            sensor_iface.ClaimAccelerometer()
        except dbus.DBusException as e:
            log.error("ClaimAccelerometer failed: %s", e)
            return False

        try:
            props = props_iface.GetAll(SENSOR_PROXY_BUS)
            self.orientation = str(props.get("AccelerometerOrientation", "undefined"))
        except dbus.DBusException as e:
            log.warning("Could not read initial properties: %s", e)

        self._find_accel_paths()
        GLib.timeout_add(TENT_POLL_MS, self._poll_tent)

        initial = self._effective_state()
        log.info(
            "Connected — orientation=%s → applying %s immediately",
            self.orientation, initial,
        )
        self._rotate_now(initial)
        return True

    def run(self):
        loop = GLib.MainLoop()
        if not self.connect():
            sys.exit(1)
        loop.run()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    RotationDaemon(bus).run()


if __name__ == "__main__":
    main()
