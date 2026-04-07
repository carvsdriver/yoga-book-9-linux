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
import ctypes
import fcntl

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

# CDC serial initialization.
#
# Source: Windows USBPcap trace (touchcap).  At t≈1.18s after USB enumeration,
# usbser.sys sends:
#   1. CDC SET_LINE_CODING (bRequest=0x20) to interface 0, data = 7-byte
#      line-coding struct: dwDTERate=115200 (0x0001c200 LE), bCharFormat=0,
#      bParityType=0, bDataBits=0.
#   2. CDC SET_CONTROL_LINE_STATE (bRequest=0x22) to interface 0, wValue=0x0003
#      (DTR=1, RTS=1).
#
# The INGENIC firmware resets within ~1.18s if no CDC init is received, and
# resets every ~20s if the CDC interface is never properly initialised.
# cdc-acm cannot bind because the data interface (1.1) uses vendor class 0xff
# with zero-length descriptor references; control requests are sent via the
# USBDEVFS_CONTROL ioctl instead, which does not require claiming the interface.
#
# Note: the original approach (HID Output report via hidraw write) used these
# same 7 bytes but sent them as an interrupt OUT to the keyboard endpoint.
# That happened to satisfy the 1.18s timer but not the 20s CDC watchdog.
CDC_LINE_CODING = bytes([0x00, 0xc2, 0x01, 0x00, 0x00, 0x00, 0x00])

class _UsbCtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_uint8),
        ("bRequest",     ctypes.c_uint8),
        ("wValue",       ctypes.c_uint16),
        ("wIndex",       ctypes.c_uint16),
        ("wLength",      ctypes.c_uint16),
        ("timeout",      ctypes.c_uint32),   # milliseconds
        ("data",         ctypes.c_void_p),
    ]


# USBDEVFS_CONTROL = _IOWR('U', 0, struct usbdevfs_ctrltransfer).
# Computed from the actual struct size so alignment padding is handled correctly
# on any platform (64-bit: sizeof=24 due to 4-byte pad before void*; would be
# 20 on 32-bit — hardcoding either value causes ENOTTY on the other).
_IOC_READ  = 2
_IOC_WRITE = 1
_USBDEVFS_CONTROL = (
    ((_IOC_READ | _IOC_WRITE) << 30) |
    (ord('U') << 8) |
    (ctypes.sizeof(_UsbCtrlTransfer) << 16)
)


SETTLE_DELAY = 0.0

# Lock directory: one flag file per USB device enumeration.
# The lock key is busnum_devnum, which is the same for all HID interfaces
# belonging to the same USB device.  This ensures CDC init is sent exactly
# once even though udev fires for multiple hidraw nodes simultaneously.
# /run is tmpfs; cleared on reboot.
LOCK_DIR = "/run/ingenic-touch-init"

# Regex matching a USB interface component in a sysfs DEVPATH.
# Example: /devices/.../3-6:1.3/0003:17EF:6161.005F/hidraw/hidraw5
_USB_IFACE_RE = re.compile(r'^(\d+-[\d.]+):\d+\.\d+$')


def sysfs_read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _usb_dev_dir_from_hidraw(dev_path):
    """
    Walk sysfs from a hidraw device node up to the parent USB device directory.
    Returns the absolute sysfs path of the USB device dir, or None on error.
    """
    node = os.path.basename(dev_path)
    try:
        hid_dir = os.path.realpath(os.path.join("/sys/class/hidraw", node, "device"))
        usb_iface = os.path.dirname(hid_dir)
        return os.path.dirname(usb_iface)
    except OSError:
        return None


def get_usb_device_lock_key(dev_path):
    """
    Return a lock key for the USB device that owns dev_path, e.g. "usb_3_23".
    Shared by all HID interfaces of the same USB enumeration.
    Returns None if sysfs is inaccessible.
    """
    usb_dev = _usb_dev_dir_from_hidraw(dev_path)
    if usb_dev is None:
        return None
    busnum = sysfs_read(os.path.join(usb_dev, "busnum"))
    devnum = sysfs_read(os.path.join(usb_dev, "devnum"))
    if busnum and devnum:
        return f"usb_{busnum}_{devnum}"
    return None


def get_usb_device_lock_key_from_devpath(devpath):
    """
    Extract the USB device lock key from a sysfs DEVPATH string.
    Used during REMOVE when the sysfs class symlink may already be gone.
    Walks up the DEVPATH to find the USB interface component, then reads
    busnum/devnum from the parent USB device directory in /sys/devices/.
    Returns None if the key cannot be determined.
    """
    # DEVPATH = /devices/.../usb3/3-6/3-6:1.3/0003:17EF:6161.005F/hidraw/hidraw5
    parts = devpath.strip('/').split('/')
    for i, part in enumerate(parts):
        if _USB_IFACE_RE.match(part):
            usb_dev_path = '/sys/' + '/'.join(parts[:i])
            busnum = sysfs_read(os.path.join(usb_dev_path, 'busnum'))
            devnum = sysfs_read(os.path.join(usb_dev_path, 'devnum'))
            if busnum and devnum:
                return f"usb_{busnum}_{devnum}"
    return None


def acquire_init_lock(dev_path):
    """
    Atomically create a lock file for this USB device enumeration.
    Returns True if we are the first (should send init), False if already done.
    Uses O_CREAT|O_EXCL for atomicity — no TOCTOU race between processes.
    All hidraw nodes belonging to the same USB device share the same key,
    so only the first process to win the lock sends the CDC init.
    """
    key = get_usb_device_lock_key(dev_path)
    if key is None:
        log.warning("Cannot determine USB device lock key; proceeding without lock.")
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
    Called on REMOVE so the lock slot is freed for the next enumeration.
    Multiple REMOVE events (one per hidraw node) are harmless: the first
    removes the file, the rest silently skip FileNotFoundError.
    """
    key = get_usb_device_lock_key_from_devpath(devpath)
    if key is None:
        log.warning("Cannot extract USB device lock key from DEVPATH: %s", devpath)
        return
    lock_path = os.path.join(LOCK_DIR, key)
    try:
        os.remove(lock_path)
        log.info("Released lock %s", key)
    except FileNotFoundError:
        pass  # already removed by another interface's REMOVE event


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


def get_usb_device_path(hidraw_dev_path):
    """
    Walk up the sysfs tree from a hidraw node to find the parent USB device,
    then return its /dev/bus/usb/BBB/DDD path.

    sysfs layout:
      /sys/class/hidraw/hidrawN/device  ->  HID device dir
        parent of HID dir               ->  USB interface dir
          parent of interface dir       ->  USB device dir (busnum, devnum)
    """
    node = os.path.basename(hidraw_dev_path)
    sysfs_node = os.path.join("/sys/class/hidraw", node)
    try:
        hid_dir      = os.path.realpath(os.path.join(sysfs_node, "device"))
        usb_iface    = os.path.dirname(hid_dir)
        usb_dev      = os.path.dirname(usb_iface)
        busnum = int(sysfs_read(os.path.join(usb_dev, "busnum")))
        devnum = int(sysfs_read(os.path.join(usb_dev, "devnum")))
        return f"/dev/bus/usb/{busnum:03d}/{devnum:03d}"
    except (OSError, TypeError, ValueError):
        return None


def _usb_ctrl(usb_fd, bRequestType, bRequest, wValue, wIndex, data_bytes):
    """
    Send one USB control transfer via USBDEVFS_CONTROL ioctl.
    Does not require claiming or detaching the interface.
    """
    if data_bytes:
        buf = (ctypes.c_uint8 * len(data_bytes))(*data_bytes)
        ptr = ctypes.cast(buf, ctypes.c_void_p).value
    else:
        buf = None
        ptr = 0
    xfer = _UsbCtrlTransfer(
        bRequestType=bRequestType,
        bRequest=bRequest,
        wValue=wValue,
        wIndex=wIndex,
        wLength=len(data_bytes) if data_bytes else 0,
        timeout=1000,
        data=ptr,
    )
    fcntl.ioctl(usb_fd, _USBDEVFS_CONTROL, xfer)
    # Keep buf alive until ioctl returns (prevent GC).
    del buf


def send_init(dev_path):
    """
    Send CDC SET_LINE_CODING and SET_CONTROL_LINE_STATE to interface 0.
    This replicates what Windows usbser.sys sends at t≈1.18s after enumeration
    to satisfy the firmware's CDC initialisation watchdog.
    """
    usb_path = get_usb_device_path(dev_path)
    if usb_path is None:
        log.error("Cannot determine USB device path for %s", dev_path)
        return False
    log.info("USB device path: %s", usb_path)

    try:
        fd = os.open(usb_path, os.O_RDWR)
    except OSError as e:
        log.error("Cannot open %s: %s", usb_path, e)
        return False

    try:
        # 1. CDC SET_LINE_CODING (bRequest=0x20): 115200 baud, 1 stop, no parity
        log.info("Sending CDC SET_LINE_CODING (115200 baud) → interface 0")
        _usb_ctrl(fd, 0x21, 0x20, 0, 0, list(CDC_LINE_CODING))

        # 2. CDC SET_CONTROL_LINE_STATE (bRequest=0x22): DTR=1, RTS=1
        log.info("Sending CDC SET_CONTROL_LINE_STATE (DTR=1, RTS=1) → interface 0")
        _usb_ctrl(fd, 0x21, 0x22, 0x0003, 0, [])

        log.info("CDC init complete.")
        return True
    except OSError as e:
        log.error("CDC init failed: %s", e)
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
