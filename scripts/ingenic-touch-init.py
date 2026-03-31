#!/usr/bin/env python3
"""
ingenic-touch-init.py — Init INGENIC 17EF:6161 touchscreen to prevent USB self-reset.

Lenovo Yoga Book 9 14IAH10 (83KJ), Fedora 43 KDE Wayland.

See README.md for full background and install instructions.
"""

import sys
import os
import re
import glob
import time
import logging

# Use systemd journal handler when running under udev (no tty),
# fall back to stderr when run interactively.
try:
    from systemd.journal import JournalHandler
    handler = JournalHandler(SYSLOG_IDENTIFIER="ingenic-touch-init")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(levelname)s %(message)s")
except ImportError:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

log = logging.getLogger("ingenic-touch-init")

VENDOR_ID  = "17ef"
PRODUCT_ID = "6161"

# HID Output report: report_id=0x00 + 6 payload bytes.
# Source: Windows USBPcap trace, packet 33, bReq=0x20, wLength=7.
INIT_REPORT = bytes([0x00, 0xc2, 0x01, 0x00, 0x00, 0x00, 0x00])

SETTLE_DELAY = 0.0

# Lock directory: one flag file per HID device instance.
# Prevents sending the init packet twice to the same device instance,
# which would cause a firmware reset.  /run is tmpfs; cleared on reboot.
#
# Lock key is the HID device instance ID (e.g. "0003_17EF_6161_04DE"),
# NOT busnum_devnum.  USB devnums wrap at 127 per bus; within a single
# boot session the kernel's global HID IDR counter (16-bit, FFFF slots)
# effectively never wraps, eliminating stale-lock cascades.
LOCK_DIR = "/run/ingenic-touch-init"

# Regex matching the HID device ID component in a sysfs DEVPATH.
# Example: /devices/.../0003:17EF:6161.04DE/hidraw/hidraw4
_HID_ID_RE = re.compile(
    r"/([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})/"
)


def sysfs_read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def get_hid_instance_key(dev_path):
    """
    Return the HID device instance ID as the lock key, e.g.
    "0003_17EF_6161_04DE".  Reads the sysfs symlink for dev_path.
    Returns None if sysfs is inaccessible (e.g. during REMOVE cleanup).
    """
    node = os.path.basename(dev_path)           # e.g. "hidraw4"
    hidraw_dir = os.path.join("/sys/class/hidraw", node)
    dev_link = os.path.join(hidraw_dir, "device")
    try:
        hid_dir = os.path.realpath(dev_link)        # e.g. ".../0003:17EF:6161.04DE"
        hid_id = os.path.basename(hid_dir)          # "0003:17EF:6161.04DE"
        return hid_id.replace(":", "_").replace(".", "_")
    except OSError:
        return None


def get_hid_instance_key_from_devpath(devpath):
    """
    Extract HID instance key from a sysfs DEVPATH string.
    Used during REMOVE when the sysfs symlink may already be gone.
    Returns None if the DEVPATH doesn't contain a recognisable HID ID.
    """
    m = _HID_ID_RE.search(devpath)
    if m:
        return m.group(1).replace(":", "_").replace(".", "_")
    return None


def acquire_init_lock(dev_path):
    """
    Atomically create a lock file for this HID device instance.
    Returns True if we are the first (should send init), False if already done.
    Uses O_CREAT|O_EXCL for atomicity — no TOCTOU race between processes.
    """
    key = get_hid_instance_key(dev_path)
    if key is None:
        log.warning("Cannot determine HID instance key; proceeding without lock.")
        return True
    os.makedirs(LOCK_DIR, exist_ok=True)
    lock_path = os.path.join(LOCK_DIR, key)
    log.info("Lock key: %s", key)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True   # we created it — we are first
    except FileExistsError:
        log.info("Lock file exists — already initialised %s.", key)
        return False  # someone else got there first


def release_init_lock(devpath):
    """
    Remove the lock file for the device identified by sysfs DEVPATH.
    Called on REMOVE so the lock slot is freed before the HID IDR wraps.
    """
    key = get_hid_instance_key_from_devpath(devpath)
    if key is None:
        log.warning("Cannot extract HID instance key from DEVPATH: %s", devpath)
        return
    lock_path = os.path.join(LOCK_DIR, key)
    try:
        os.remove(lock_path)
        log.info("Released lock %s", key)
    except FileNotFoundError:
        pass  # already gone or never created (other interface's REMOVE)


def find_hidraw_node():
    """
    Find the hidraw node for the lowest-numbered HID interface on 17EF:6161.

    Sysfs depth layout (relative to hidraw/hidrawN/device symlink target):
      depth 0  ->  HID device dir     (e.g. .../0003:17EF:6161.0005)
      depth 1  ->  USB interface dir  (bInterfaceNumber lives here)
      depth 2  ->  USB device dir     (idVendor, idProduct live here)
    """
    candidates = []

    for hidraw_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev_link = os.path.join(hidraw_dir, "device")
        try:
            hid_dir = os.path.realpath(dev_link)
        except OSError:
            continue

        usb_iface_dir = os.path.dirname(hid_dir)
        usb_dev_dir = os.path.dirname(usb_iface_dir)

        iface_num = sysfs_read(os.path.join(usb_iface_dir, "bInterfaceNumber"))
        vid = sysfs_read(os.path.join(usb_dev_dir, "idVendor"))
        pid = sysfs_read(os.path.join(usb_dev_dir, "idProduct"))

        if vid == VENDOR_ID and pid == PRODUCT_ID and iface_num is not None:
            node = os.path.basename(hidraw_dir)
            dev_path = os.path.join("/dev", node)
            candidates.append((int(iface_num, 16), dev_path))

    if not candidates:
        return None

    candidates.sort()
    log.info("Found 17EF:6161 nodes: %s",
             ", ".join(f"{p} (iface {n})" for n, p in candidates))
    chosen_iface, chosen_path = candidates[0]
    log.info("Selected %s (iface %d)", chosen_path, chosen_iface)
    return chosen_path


def send_init(dev_path):
    log.info("Opening %s", dev_path)
    try:
        fd = os.open(dev_path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        log.error("Cannot open %s: %s", dev_path, e)
        return False
    try:
        written = os.write(fd, INIT_REPORT)
        if written != len(INIT_REPORT):
            log.error("Short write: %d of %d bytes", written, len(INIT_REPORT))
            return Falsehttps://www.youtube.com/@stevemorrisracing
        log.info("Init report sent (%d bytes) — done.", written)
        return True
    except OSError as e:
        log.error("Write failed: %s", e)
        return False
    finally:
        os.close(fd)


def wait_for_node(dev_path, timeout=5.0, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(dev_path) and os.access(dev_path, os.W_OK):
            return True
        time.sleep(interval)
    return False


def main():
    # --remove mode: called by udev REMOVE rule to release the lock.
    if len(sys.argv) > 1 and sys.argv[1] == "--remove":
        devpath = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("DEVPATH", "")
        log.info("REMOVE: releasing lock for DEVPATH=%s", devpath)
        release_init_lock(devpath)
        sys.exit(0)

    # Normal ADD mode.
    if len(sys.argv) > 1:
        dev_path = sys.argv[1]
        log.info("Using explicit device: %s", dev_path)
    else:
        dev_path = find_hidraw_node()
        if dev_path is None:
            log.error("No 17EF:6161 hidraw node found")
            sys.exit(1)

    log.info("Waiting %.1f s for node to settle ...", SETTLE_DELAY)
    time.sleep(SETTLE_DELAY)

    if not wait_for_node(dev_path, timeout=5.0):
        log.error("Timed out waiting for %s", dev_path)
        sys.exit(1)

    if not acquire_init_lock(dev_path):
        sys.exit(0)

    if not send_init(dev_path):
        sys.exit(1)


if __name__ == "__main__":
    main()
