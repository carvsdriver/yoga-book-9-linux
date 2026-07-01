#!/usr/bin/env python3
"""
btreg.py - Extract Bluetooth pairing keys from Windows registry
for use with Linux dual boot on Lenovo Yoga Book 9i.

Run with: sudo python3 btreg.py
"""

import hivex
import struct
import subprocess
import os
import sys
import tempfile
import json


def find_windows_partition():
    """Find the Windows partition by looking for NTFS volumes with a Windows directory."""
    result = subprocess.run(
        ["lsblk", "-o", "NAME,FSTYPE,SIZE,MOUNTPOINT", "-J"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    ntfs_partitions = []

    def collect(devices):
        for d in devices:
            if d.get("fstype") == "ntfs":
                ntfs_partitions.append(f"/dev/{d['name']}")
            for child in d.get("children", []):
                collect([child])

    collect(data["blockdevices"])

    if not ntfs_partitions:
        print("❌ No NTFS partitions found.")
        sys.exit(1)

    mount_dir = tempfile.mkdtemp(prefix="win_bt_")

    for part in ntfs_partitions:
        try:
            subprocess.run(["mount", "-o", "ro", part, mount_dir],
                           check=True, capture_output=True)
            if os.path.exists(os.path.join(mount_dir, "Windows", "System32", "config", "SYSTEM")):
                print(f"✅ Found Windows partition: {part} (mounted at {mount_dir})")
                return mount_dir
            else:
                subprocess.run(["umount", mount_dir], capture_output=True)
        except subprocess.CalledProcessError:
            continue

    print("❌ Could not find a Windows installation on any NTFS partition.")
    subprocess.run(["rmdir", mount_dir], capture_output=True)
    sys.exit(1)


def extract_bt_keys(mount_dir):
    hive_path = os.path.join(mount_dir, "Windows", "System32", "config", "SYSTEM")
    h = hivex.Hivex(hive_path)

    def find_node(root, path):
        node = root
        for part in path:
            node = h.node_get_child(node, part)
            if node is None:
                raise Exception(f"Registry path not found: {part}")
        return node

    root = h.root()
    keys_node = find_node(root, [
        "ControlSet001", "Services", "BTHPORT", "Parameters", "Keys"
    ])

    print("\n=== Bluetooth Keys from Windows Registry ===\n")

    for adapter in h.node_children(keys_node):
        adapter_mac = h.node_name(adapter)
        adapter_fmt = ":".join(adapter_mac[i:i+2] for i in range(0, 12, 2)).upper()
        print(f"Adapter MAC: {adapter_fmt}")

        for device in h.node_children(adapter):
            device_mac = h.node_name(device)
            device_fmt = ":".join(device_mac[i:i+2] for i in range(0, 12, 2)).upper()
            print(f"\n  Device MAC: {device_fmt}")
            print(f"  Linux info file: /var/lib/bluetooth/{adapter_fmt}/{device_fmt}/info")
            print("  ┌─ Values to update:")

            for val in h.node_values(device):
                name = h.value_key(val)
                raw = h.value_value(val)[1]
                name_upper = name.upper()

                if name_upper == "LTK":
                    print(f"  │  [LongTermKey] Key={raw.hex().upper()}")
                elif name_upper == "ERand":
                    dec = struct.unpack('<Q', raw)[0]
                    print(f"  │  Rand={dec}")
                elif name_upper == "EDIV":
                    fmt = '<I' if len(raw) == 4 else '<H'
                    dec = struct.unpack(fmt, raw)[0]
                    print(f"  │  EDiv={dec}")
                elif name_upper == "IRK":
                    print(f"  │  [IdentityResolvingKey] Key={raw.hex().upper()}")
                elif name_upper == "CSRK":
                    print(f"  │  [LocalSignatureKey] Key={raw.hex().upper()}")

            print("  └─")


def cleanup(mount_dir):
    subprocess.run(["umount", mount_dir], capture_output=True)
    subprocess.run(["rmdir", mount_dir], capture_output=True)
    print(f"\n✅ Unmounted and cleaned up {mount_dir}")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("❌ This script must be run as root (sudo).")
        sys.exit(1)

    mount_dir = find_windows_partition()
    try:
        extract_bt_keys(mount_dir)
    finally:
        cleanup(mount_dir)
