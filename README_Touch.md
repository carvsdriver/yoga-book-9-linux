# Lenovo Yoga Book 9 14IAH10 (83KJ) — Linux Touchscreen Fix

## Summary

This documents the complete investigation and fix for non-functional touchscreens
on the Lenovo Yoga Book 9 14IAH10 (83KJ) running Fedora 43 / Linux 6.19.

Two separate bugs were fixed:

1. **USB reset loop** — The INGENIC touchscreen controller resets itself unless
   it receives a specific HID Output report within ~1.18 seconds of USB
   enumeration. Fixed with a udev rule + Python script.

2. **Touch misclassified as clickpad** — The kernel's `hid-multitouch` driver
   incorrectly sets `INPUT_PROP_BUTTONPAD` on the touchscreen input devices,
   causing libinput to treat them as indirect clickpads. Fixed with a kernel
   module patch.

---

## Part 1: USB Reset Loop

### Discovery

The touchscreen device (`17EF:6161`) was repeatedly disconnecting and
reconnecting in `dmesg`, producing log spam and intermittent touch failures.
Initial investigation pointed to the INGENIC USB controller resetting itself
after enumeration.

### Windows USB Capture

A USBPcap trace was captured on Windows to observe what the Windows HID driver
sends to the device that Linux does not. Analysing `touchcap.pcap` (534 packets)
revealed the following sequence approximately 1.18 seconds after
`SELECT_CONFIGURATION`:

| Pkt | Request | Details |
|-----|---------|---------|
| 27 | SET_IDLE | wIdx=2 — silence iface 2 idle reports |
| 28 | SET_IDLE | wIdx=4 — silence iface 4 idle reports |
| **33** | **SET_REPORT** | **bmReq=0x21, bReq=0x20, wValue=0x0000, wIndex=0, wLength=7** |
| 51 | GET_REPORT | Windows reads back to confirm |

Packet 33 is the critical init command. The 7-byte payload is:
```
00 c2 01 00 00 00 00
```

### Implementation Notes

`bRequest=0x20` is a **HID Output report** — not a Feature report.
- `HIDIOCSFEATURE` ioctl sends `bRequest=0x09` (Feature) — **wrong**
- `write()` on a hidraw fd sends `bRequest=0x20` (Output) — **correct**

The composite device has 7 interfaces (0–6). Interfaces 2–6 expose hidraw
nodes; interface 0 has no HID function. The correct hidraw node is identified
by finding the 17EF:6161 device with the lowest `bInterfaceNumber` (interface 2,
typically `/dev/hidraw4`).

The udev rule uses `ENV{ID_VENDOR_ID}` and `ENV{ID_MODEL_ID}` rather than
`ATTRS{idVendor}` because `ATTRS{}` walks the sysfs ancestor chain independently
for each attribute and can match against the USB hub (`idVendor=1d6b`) instead
of the device.

### Files

- `scripts/ingenic-touch-init.py` — Finds the correct hidraw node and sends
  the init Output report
- `scripts/99-ingenic-touch-init.rules` — udev rule firing on
  `SUBSYSTEM=hidraw, ENV{ID_VENDOR_ID}=17ef, ENV{ID_MODEL_ID}=6161,
  ATTRS{bInterfaceNumber}=02`

### Install

```bash
sudo cp ingenic-touch-init.py /usr/local/sbin/
sudo chmod +x /usr/local/sbin/ingenic-touch-init.py
sudo cp 99-ingenic-touch-init.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

---

## Part 2: Touch Misclassified as Clickpad

### Discovery

After fixing the USB reset loop, `evtest` confirmed touch events flowing from
the kernel. However, libinput showed no `touch` capability and KDE did not
respond to touch input.

Investigation revealed `INPUT_PROP_BUTTONPAD` (bit 2) set on both touchscreen
input devices, causing libinput to treat them as indirect clickpads.

### Root Cause

The device shares USB PID `0x6161` with the Yoga Book 9i and is handled by
`MT_CLS_YOGABOOK9I` in `hid-multitouch`. Three separate firmware quirks
triggered incorrect property assignment:

**Quirk 1: Stylus buttons inside touchscreen collections**

The HID report descriptor places stylus button usages (`HID_UP_BUTTON`) inside
`HID_DG_TOUCHSCREEN` application collections. The generic heuristic in
`mt_touch_input_mapping()` treats any touchscreen-with-buttons as a touchpad,
setting `INPUT_MT_POINTER`.

**Quirk 2: Emulated touchpad application**

The `HID_DG_TOUCHPAD` application collection (the emulated touchpad) sets
`INPUT_MT_POINTER` unconditionally in `mt_allocate_application()`, which
propagates to all input devices sharing the same `hid_input`.

**Quirk 3: PadType feature report returns Clickpad**

The `HID_DG_BUTTONTYPE` feature report (report 0x51) returns
`MT_BUTTONTYPE_CLICKPAD` (value 2), directly setting `td->is_buttonpad = true`
in `mt_input_mapping()`.

### HID-BPF Descriptor Patching (Intermediate Approach)

A HID-BPF program (`0010-INGENIC__Gadget-touchscreen.bpf.c`) was developed and
deployed via `udev-hid-bpf` to patch the report descriptor, neutralising the
Microsoft PTP certification blobs (`Usage 0xc5` → `0xc6`) that trigger
`HID_GROUP_MULTITOUCH_WIN_8` classification. While this successfully removed
`INPUT_PROP_BUTTONPAD`, it also broke `INPUT_PROP_DIRECT` assignment because
losing the WIN_8 group removed the named device creation logic
(`Touchscreen Top`/`Touchscreen Bottom`).

The BPF approach was retained in the stack for the USB reset fix validation
but the root fix requires a kernel patch.

### Kernel Fix

The correct fix is a patch to `drivers/hid/hid-multitouch.c` that skips the
three problematic heuristics when `MT_QUIRK_YOGABOOK9I` is set:

```c
/* 1. Skip touchpad POINTER flag for YOGABOOK9I */
if (application == HID_DG_TOUCHPAD &&
    !(td->mtclass.quirks & MT_QUIRK_YOGABOOK9I)) {
    mt_application->mt_flags |= INPUT_MT_POINTER;
    ...
}

/* 2. Skip button-in-touchscreen heuristic for YOGABOOK9I */
if (field->application == HID_DG_TOUCHSCREEN &&
    (usage->hid & HID_USAGE_PAGE) == HID_UP_BUTTON) {
    if (!(app->quirks & MT_QUIRK_YOGABOOK9I)) {
        app->mt_flags |= INPUT_MT_POINTER;
        ...
    }
}

/* 3. Skip BUTTONTYPE_CLICKPAD for YOGABOOK9I */
case HID_DG_BUTTONTYPE:
    if (td->mtclass.quirks & MT_QUIRK_YOGABOOK9I)
        break;
    ...

/* 4. Skip is_buttonpad check for YOGABOOK9I */
if ((app->mt_flags & INPUT_MT_POINTER) &&
    (app->buttons_count == 1) &&
    !(app->quirks & MT_QUIRK_YOGABOOK9I))
    td->is_buttonpad = true;
```

### Result

After applying the kernel patch:
- `props=0x02` = `INPUT_PROP_DIRECT` only (no BUTTONPAD, no POINTER)
- libinput correctly identifies both screens as `cap:t` (touch, direct)
- KDE/Wayland responds to touch on both displays
- On-screen keyboard appears on touch as expected

### Files

- `scripts/0001-HID-multitouch-Fix-Lenovo-Yoga-Book-9-touchscreen-INPUT_PROP.patch`
  — Upstream kernel patch for `drivers/hid/hid-multitouch.c`
- `scripts/0010-INGENIC__Gadget-touchscreen.bpf.c` — HID-BPF program
  (deployed via udev-hid-bpf, provides belt-and-suspenders descriptor fixup)

### Kernel Module Install (Until Patch Upstreamed)

```bash
# Requires kernel-devel for running kernel
cd ~/projects/udev-hid-bpf  # or wherever kernel-src lives
cp scripts/0001-HID-multitouch-Fix-Lenovo-Yoga-Book-9-touchscreen-INPUT_PROP.patch \
   ~/kernel-src/
cd ~/kernel-src
patch -p1 < 0001-HID-multitouch-Fix-Lenovo-Yoga-Book-9-touchscreen-INPUT_PROP.patch
make
sudo zstd -19 hid-multitouch.ko \
    -o /lib/modules/$(uname -r)/kernel/drivers/hid/hid-multitouch.ko.zst
sudo depmod
sudo reboot
```

---

## Property Bitmap Reference

The sysfs `properties` file for input devices is a hex bitmask:

| Bit | Value | Constant | Meaning |
|-----|-------|----------|---------|
| 0 | 0x01 | `INPUT_PROP_POINTER` | Needs a pointer (mouse, trackpad) |
| 1 | 0x02 | `INPUT_PROP_DIRECT` | Direct touch surface (touchscreen) |
| 2 | 0x04 | `INPUT_PROP_BUTTONPAD` | Has button under pad (clickpad) |
| 7 | 0x80 | `INPUT_PROP_SOFTCOMBINATION` | Soft key combination device |

Before fix: `props=0x86` = DIRECT + BUTTONPAD + SOFTCOMBINATION
After fix:  `props=0x02` = DIRECT only
