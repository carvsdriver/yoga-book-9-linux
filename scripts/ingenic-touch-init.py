#!/usr/bin/env python3
"""
ingenic-touch-init.py — Init INGENIC 17EF:6161 touchscreen to prevent USB self-reset.

Lenovo Yoga Book 9 14IAH10 (83KJ), Fedora 43 KDE Wayland.

See README.md for full background and install instructions.
"""

import sys
import os
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

SETTLE_DELAY = 0.5


def sysfs_read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


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
        usb_dev_dir   = os.path.dirname(usb_iface_dir)

        iface_num = sysfs_read(os.path.join(usb_iface_dir, "bInterfaceNumber"))
        vid       = sysfs_read(os.path.join(usb_dev_dir,   "idVendor"))
        pid       = sysfs_read(os.path.join(usb_dev_dir,   "idProduct"))

        if vid == VENDOR_ID and pid == PRODUCT_ID and iface_num is not None:
            node     = os.path.basename(hidraw_dir)
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
            return False
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

    if not send_init(dev_path):
        sys.exit(1)


if __name__ == "__main__":
    main()
