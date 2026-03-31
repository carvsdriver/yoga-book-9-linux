# Lenovo Yoga Book 9 14IAH10 (83KJ) — Linux Touchscreen Fix

## Summary

This documents the complete investigation and fix for non-functional touchscreens
on the Lenovo Yoga Book 9 14IAH10 (83KJ) running Fedora 43 / Linux 6.19.

Three separate bugs were fixed:

1. **USB reset loop** — The INGENIC touchscreen controller resets itself unless
   it receives a specific HID Output report within ~1.18 seconds of USB
   enumeration. Fixed in the kernel patch (Part 2), with a udev rule + Python
   script as a belt-and-suspenders fallback.

2. **Touch misclassified as clickpad** — The kernel's `hid-multitouch` driver
   incorrectly sets `INPUT_PROP_BUTTONPAD` on the touchscreen input devices,
   causing libinput to treat them as indirect clickpads. Fixed with a kernel
   module patch.

3. **Emulated touchpad causes on-screen keyboard freezes** — The composite USB
   device exposes a redundant `HID_DG_TOUCHPAD` collection which hid-multitouch
   turns into a pointer input node. Every finger tap generates a duplicate
   mouse-click event that steals compositor focus from the on-screen keyboard.
   Fixed with a udev rule.

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

A HID-BPF program (`0010-INGENIC__Gadget-touchscreen.bpf.c`) was developed as
an alternative to the kernel patch. It patches three `BTN_LEFT` (`Usage 0x01`)
bytes in the report descriptor to `BTN_SIDE` (`Usage 0x04`), which stops
`hid-multitouch` from setting `INPUT_PROP_BUTTONPAD`.

The initial version (`10-INGENIC__Gadget-touchscreen.bpf.c`) patched the
Microsoft PTP certification blobs (`Usage 0xc5` → `0xc6`). While it removed
`INPUT_PROP_BUTTONPAD`, it also broke `INPUT_PROP_DIRECT` assignment because
losing `HID_GROUP_MULTITOUCH_WIN_8` removed the named device creation logic
(`Touchscreen Top`/`Touchscreen Bottom`). The revised version (`0010-`) leaves
the cert blobs intact and patches only the button usages instead.

The BPF approach provides the same property fix without replacing the kernel
module. It can be used standalone or alongside the kernel patch. The root fix
for upstreaming is the kernel patch.

#### Building the BPF Program

```bash
# Prerequisites
sudo dnf install clang llvm libbpf-devel bpftool kernel-devel-$(uname -r)

# Generate vmlinux.h from the running kernel's BTF data
cd ~/kernel-src/bpf
bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h

# Compile (target bpf, optimise, embed BTF)
clang -O2 -g -target bpf \
    -D__KERNEL__ \
    -I./progs \
    -I/usr/include \
    -c ~/projects/yoga9ibook/scripts/0010-INGENIC__Gadget-touchscreen.bpf.c \
    -o 0010-INGENIC__Gadget-touchscreen.bpf.o

# Strip to a clean object (optional but reduces size)
llvm-strip -g 0010-INGENIC__Gadget-touchscreen.bpf.o
```

#### Deploying via udev-hid-bpf

`udev-hid-bpf` discovers and loads BPF programs automatically when the matching
USB device is added. Programs are stored in
`/usr/lib/udev/hid-bpf/` (system) or `/etc/udev/hid-bpf/` (local override).

```bash
# Install udev-hid-bpf if not already present
sudo dnf install udev-hid-bpf
# or build from source: https://gitlab.freedesktop.org/libevdev/udev-hid-bpf

# Deploy the compiled program
sudo udev-hid-bpf install 0010-INGENIC__Gadget-touchscreen.bpf.o

# Reload udev rules and trigger the device
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hid
```

To uninstall:

```bash
sudo udev-hid-bpf remove 0010-INGENIC__Gadget-touchscreen.bpf.o
sudo udevadm control --reload-rules
```

Verify the program loaded:

```bash
# Should show the ingenic_touchscreen program attached
bpftool prog list | grep ingenic
# or
sudo udev-hid-bpf list
```

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

- `scripts/0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen.patch`
  — Kernel patch for `drivers/hid/hid-multitouch.c` (clickpad fix + USB reset
  loop fix + emulated touchpad class entry)
- `scripts/hid-multitouch.c` — Patched source file for reference / direct use
- `scripts/0010-INGENIC__Gadget-touchscreen.bpf.c` — HID-BPF program
  (alternative to kernel patch; patches `BTN_LEFT` offsets in the descriptor)

### Kernel Module Install (Until Patch Upstreamed)

#### Step 1 — Download the Kernel Source

The out-of-tree build only needs two files from the kernel tree:
`drivers/hid/hid-multitouch.c` and `drivers/hid/hid-ids.h`.

```bash
# Install build prerequisites
sudo dnf install kernel-devel-$(uname -r) rpm-build

# Download the source RPM for the exact running kernel
# (strips the architecture suffix, e.g. 6.19.10-200.fc43)
sudo dnf download --source kernel-$(uname -r | sed 's/\.[^.]*$//')

# Extract the kernel tarball from the source RPM
rpm2cpio kernel-*.src.rpm | cpio -idmv '*.tar.xz'
# Produces linux-X.Y.Z.tar.xz in the current directory

# Create the build directory
mkdir -p ~/kernel-src
cd ~/kernel-src

# Extract only the two HID driver files
KVER=$(ls ../linux-*.tar.xz | grep -oP 'linux-\K[0-9.]+(?=\.tar)')
tar xf ../linux-${KVER}.tar.xz --strip-components=3 \
    linux-${KVER}/drivers/hid/hid-multitouch.c \
    linux-${KVER}/drivers/hid/hid-ids.h

# Create the out-of-tree Makefile
cat > Makefile << 'EOF'
obj-m := hid-multitouch.o
EOF
```

> **Note:** The version in the source RPM may be one micro-release behind the
> running kernel (e.g. source is `6.19.9`, running kernel is `6.19.10`).
> Check with `uname -r` and compare to the tarball name. For ABI-compatible
> point releases the source file is identical; apply the patch and build
> against the running kernel's headers regardless.

#### Step 2 — Apply the Patch and Build

```bash
cd ~/kernel-src
cp ~/projects/yoga9ibook/scripts/0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen.patch .
patch -p1 < 0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen.patch

# Build against the running kernel's headers
make -C /usr/src/kernels/$(uname -r) M=$(pwd) modules
```

#### Step 3 — Install

```bash
# Compress and install
zstd -f -19 hid-multitouch.ko -o hid-multitouch.ko.zst
sudo cp hid-multitouch.ko.zst \
    /lib/modules/$(uname -r)/kernel/drivers/hid/hid-multitouch.ko.zst
sudo depmod -a

# Reload without rebooting
sudo rmmod hid_multitouch && sudo modprobe hid_multitouch
# or reboot
```

> **Tip:** Save the original before overwriting so you can restore it:
> ```bash
> sudo cp /lib/modules/$(uname -r)/kernel/drivers/hid/hid-multitouch.ko.zst \
>          ~/kernel-src/hid-multitouch.ko.zst.orig
> ```

---

## Part 3: Emulated Touchpad Causes On-Screen Keyboard Freezes

### Discovery

After fixing the USB reset loop and clickpad misclassification, the on-screen
keyboard (both KDE's built-in OSK and Maliit) would freeze or dismiss
mid-interaction when typing on either touchscreen.

Investigation with `libinput list-devices` revealed a third input node:

```
Device:           INGENIC Gadget Serial and keyboard Emulated Touchpad
Kernel:           /dev/input/event22
Group:            9
Seat:             seat0, default
Capabilities:     pointer touch
Tap-to-click:     disabled
...
```

### Root Cause

The `17EF:6161` composite device's HID descriptor includes a `HID_DG_TOUCHPAD`
application collection alongside the two `HID_DG_TOUCHSCREEN` collections.
`hid-multitouch` creates a separate input node for it — the "Emulated Touchpad"
— which libinput classifies as having both pointer and touch capabilities.

Every finger tap on either touchscreen fires **two independent event streams**:

1. **Touchscreen Top/Bottom** (`EV_ABS` multitouch) → the compositor routes
   these via touch focus to the active touch target — correct.
2. **Emulated Touchpad** (`EV_BTN` + pointer motion at the same coordinate) →
   the compositor interprets this as a mouse click at that screen position,
   hitting whatever window is behind the on-screen keyboard and stealing
   focus — causing the OSK to freeze or dismiss.

### Fix

A udev rule sets `LIBINPUT_IGNORE_DEVICE=1` on the emulated touchpad node.
libinput then never opens the device and the duplicate pointer events are
suppressed. The real touchscreen nodes handle all touch input; the emulated
touchpad is fully redundant.

### Install

```bash
sudo cp scripts/91-ingenic-emulated-touchpad.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input --action=add
```

### Verify

```bash
# Find the emulated touchpad event node
grep -r "Emulated Touchpad" /sys/class/input/*/device/name 2>/dev/null

# Check the udev property is set (replace eventN with the node above)
sudo udevadm info /dev/input/eventN | grep LIBINPUT_IGNORE
# Expected: E: LIBINPUT_IGNORE_DEVICE=1

# Confirm libinput no longer sees it
sudo libinput list-devices | grep -A4 "Emulated Touchpad"
# Expected: no output (device absent from libinput's list)
```

### Files

- `scripts/91-ingenic-emulated-touchpad.rules` → `/etc/udev/rules.d/`

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
