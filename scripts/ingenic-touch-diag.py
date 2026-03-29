#!/usr/bin/env python3
"""
ingenic-touch-diag.py — Dump sysfs layout for all hidraw nodes.
Run as root: sudo python3 ingenic-touch-diag.py
"""
import os, glob

for hidraw_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
    node = os.path.basename(hidraw_dir)
    dev_link = os.path.join(hidraw_dir, "device")
    try:
        real_dev = os.path.realpath(dev_link)
    except OSError as e:
        print(f"{node}: realpath error: {e}")
        continue

    print(f"\n{'='*60}")
    print(f"{node}  →  {real_dev}")

    # Walk every ancestor up to 8 levels, print any interesting attributes
    path = real_dev
    for depth in range(10):
        attrs = {}
        for attr in ["bInterfaceNumber", "idVendor", "idProduct",
                     "busnum", "devnum", "uevent", "modalias"]:
            val = None
            try:
                with open(os.path.join(path, attr)) as f:
                    val = f.read().strip()
            except OSError:
                pass
            if val is not None:
                attrs[attr] = val

        if attrs:
            print(f"  depth={depth}  {path}")
            for k, v in attrs.items():
                print(f"    {k} = {v!r}")

        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
