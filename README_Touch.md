# Lenovo Yoga Book 9 14IAH10 (83KJ) — Linux Touchscreen Fix

## Summary

This documents the complete investigation and fix for non-functional touchscreens
on the Lenovo Yoga Book 9 14IAH10 (83KJ) running Fedora 43 / Linux 6.19.

## Upstream Status

Kernel patches have been submitted to the Linux kernel mailing lists:

| Patch | List | Link |
|-------|------|------|
| `cdc-acm`: VENDOR_CLASS_DATA_IFACE + ALWAYS_POLL_CTRL quirks for 17EF:6161 (0002) | linux-usb | **Merged to mainline** 2026-04-19 (v7.1-rc1) — [f58752ebcb35](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f58752ebcb35e156c85cd1a82d6579c7af3b9023) |
| `cdc-acm`: start bulk-IN polling when ALWAYS_POLL_CTRL is set (0005) | linux-usb | **Merged to usb-next** 2026-05-27 (Greg KH) — will be in next major release |
| `hid-multitouch`: Fix Yoga Book 9 14IAH10 touchscreen misclassification (v2) | linux-input | **Applied to hid/for-next** 2026-05-12 — [lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/](https://lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/) |
| `hid-multitouch`: Fix stale MT slots when contact count drops to zero | linux-input | v1 submitted 2026-05-15; v2 submitted 2026-05-22 (restructured per bentiss review) |
| `hid-multitouch`: Honor ContactCount to suppress stale-slot ghost contacts | linux-input | Submitted 2026-05-14; awaiting review — Message-ID: &lt;CALPvRORBFHpbos=_xpBVchK-oSZF9EnY6n5-sAQGr=qiL13FbQ@mail.gmail.com&gt; |
| `lenovo-yb9-kbdock`: Keyboard dock detection (SW_TABLET_MODE + sysfs) | platform-driver-x86 | v5 submitted 2026-05-27 — Message-ID: &lt;20260527122701.242907-1-carvsdriver@gmail.com&gt; |

Until all patches land in a released kernel, the out-of-tree build instructions
below are required. The cdc-acm quirk patch is merged to mainline and will ship
in kernel 7.1. The hid-multitouch misclassification fix (v2) is applied to
hid/for-next and expected in the next merge window. All other patches are
submitted and awaiting upstream review.

---

Three separate bugs were fixed:

1. **USB reset loop** — The INGENIC touchscreen controller (interface 0, CDC ACM)
   performs a fixed 4-connection boot sequence on every power cycle: it resets
   the USB bus ~4 times at ~19 s intervals before stabilising. Linux's `cdc-acm`
   driver failed to bind because the CDC data interface declares vendor-specific
   class (`0xff`), causing interface 0 to remain unbound and leaving the firmware
   in a continuous reset loop. Fixed with two cdc-acm kernel patches: patch 0004
   (`VENDOR_CLASS_DATA_IFACE` + `ALWAYS_POLL_CTRL` quirks) and patch 0005 (bulk-IN
   polling to suppress a secondary ~55 s firmware watchdog). Touch becomes
   available ~60–80 s after boot due to the firmware's fixed reset sequence.

2. **Touch misclassified as clickpad** — The kernel's `hid-multitouch` driver
   incorrectly sets `INPUT_PROP_BUTTONPAD` on the touchscreen input devices,
   causing libinput to treat them as indirect clickpads. Fixed with a kernel
   module patch.

3. **Emulated touchpad causes on-screen keyboard freezes** — The composite USB
   device exposes a redundant `HID_DG_TOUCHPAD` collection which hid-multitouch
   turns into a pointer input node. Every finger tap generates a duplicate
   mouse-click event that steals compositor focus from the on-screen keyboard.
   Fixed with a udev rule.

4. **Keyboard dock not reported to userspace** — The detachable Bluetooth
   keyboard magnetically attaches to the bottom screen in one of two positions.
   The EC tracks state in a 2-bit BKBD field and signals changes via WMI notify
   0xEB. Without a driver, userspace (e.g., KDE Plasma, screen-rotation daemons)
   has no way to know whether the keyboard is present or what orientation to
   use. Fixed with the `lenovo-yb9-kbdock` kernel driver.

---

## Part 1: USB Reset Loop

### Discovery

The touchscreen device (`17EF:6161`) was repeatedly disconnecting and
reconnecting in `dmesg`, producing log spam and no touch input. Without the
cdc-acm patch below, the device is in a **continuous reset loop** — it never
stabilises.

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

Packet 33 has `bmRequestType=0x21` (Host→Device, Class, Interface) and
`bRequest=0x20`. This is the **CDC `SET_LINE_CODING`** command, not a HID Output
report. Windows loads `usbser.sys` for interface 0 (CDC ACM class), which sends
this standard serial initialisation sequence; Linux binds the HID interfaces but
leaves interface 0 completely unbound.

The 7-byte payload encodes a line-coding struct: 115200 baud, 1 stop bit,
no parity:
```
00 c2 01 00 00 00 00
```
(`dwDTERate=0x0001c200` LE = 115200, `bCharFormat=0`, `bParityType=0`,
`bDataBits=0`)

### Root Cause

Interface 0 of the composite device is a standard CDC ACM control interface
(class `0x02`, subclass `0x02`, protocol `0x01`) with a single interrupt-IN
endpoint (EP `0x82`). Interface 1 is the paired data interface, but it
incorrectly declares vendor-specific class (`0xff`) instead of
`USB_CLASS_CDC_DATA` (`0x0a`). This causes the Linux `cdc-acm` driver to reject
the device at probe time with `-EINVAL`, leaving interface 0 entirely unbound and
EP `0x82` never polled.

With the patched driver, `cdc-acm` binds interface 0 and the following
sequence is established per USB connection (confirmed with `cdc_acm.dyndbg=+p`):

1. `SET_LINE_CODING` (bRequest=0x20) — firmware acknowledges
2. `SET_CONTROL_LINE_STATE` (bRequest=0x22, val=0x3 = DTR+RTS) — firmware acknowledges
3. Firmware sends exactly **one** `SERIAL_STATE(0x3)` notification on EP 0x82
4. `ctrlurb` receives the notification and resubmits, polling continuously
5. ~19 seconds later: firmware initiates a USB disconnect+reconnect

This 4-step cycle repeats **exactly 4 times** on every fresh boot (power cycle).
After the 4th cycle the firmware stabilises and remains connected indefinitely.
The 4-cycle boot sequence is a fixed firmware property; its timing and count
cannot be altered from the host side. The only way to avoid it is a firmware
update.

### Boot Timing

Because the firmware performs 4 × ~19 s reset cycles, touch is not available
until approximately **75–80 seconds after the USB device first enumerates**.
On a typical boot the device enumerates before the login screen appears, so
the effective wait from login to working touch is roughly **40–60 seconds**
depending on how quickly the system boots to the login prompt.

This delay is expected and unavoidable with the current firmware. Extensive
debugging confirmed that neither rapid driver-side SET_CONTROL_LINE_STATE
toggles, keepalive polling, nor forced USB bus resets reduce the cycle count —
all of these either have no effect or cause the firmware to enter longer reset
sequences.

### Kernel Fix (cdc-acm patch)

The definitive fix is a patch to `drivers/usb/class/cdc-acm.c` and
`drivers/usb/class/cdc-acm.h` that adds two new quirk bits and a device ID
table entry for `17EF:6161`:

```c
/* cdc-acm.h */
#define VENDOR_CLASS_DATA_IFACE  BIT(9)   /* data interface uses vendor-specific class */
#define ALWAYS_POLL_CTRL         BIT(10)  /* poll notification endpoint even with no TTY open */

/* cdc-acm.c — ID table */
{ USB_DEVICE_INTERFACE_CLASS(0x17ef, 0x6161, USB_CLASS_COMM),
  .driver_info = VENDOR_CLASS_DATA_IFACE | ALWAYS_POLL_CTRL },
```

**`VENDOR_CLASS_DATA_IFACE`** — bypasses the `bInterfaceClass != USB_CLASS_CDC_DATA`
check in `acm_probe()` that would otherwise return `-EINVAL` for the vendor-class
data interface.

**`ALWAYS_POLL_CTRL`** — submits the notification URB (`ctrlurb`) at probe time,
before any TTY is opened. Without this flag cdc-acm only polls the notification
endpoint while a TTY device is held open; with it, polling starts immediately at
`probe()` and resumes automatically after `port_shutdown()` and after system
resume, keeping the notification endpoint watchdog suppressed.

Changes in `cdc-acm.c` (patch 0004):
1. `acm_port_activate()` — skip ctrlurb submit (already running) when `ALWAYS_POLL_CTRL`
2. `acm_port_shutdown()` — resubmit ctrlurb after port closes when `ALWAYS_POLL_CTRL`
3. `acm_resume()` — submit ctrlurb on resume even without an open TTY
4. `acm_probe()` — submit ctrlurb immediately after `dev_info("ttyACM%d")` when `ALWAYS_POLL_CTRL`

### Bulk-IN Watchdog Fix (patch 0005)

After deploying patch 0004 a second watchdog was discovered: the firmware
monitors bulk-IN activity on interface 1 (the data endpoint, EP 0x81) in
addition to the notification endpoint. With no TTY open, `cdc-acm` stops
submitting read URBs after `port_shutdown()`. The firmware detects the idle
bulk-IN endpoint and resets the USB bus approximately every **55 seconds**.

Keeping ctrlurb active (0002) alone is insufficient — EP 0x82 activity
satisfies the notification watchdog but the firmware separately tracks whether
EP 0x81 is being read. Patch 0003 adds `acm_submit_read_urbs()` calls to
both `ALWAYS_POLL_CTRL` paths:

Changes in `cdc-acm.c` (patch 0005):
5. `acm_probe()` — start bulk-IN polling (`acm_submit_read_urbs`) immediately at probe when `ALWAYS_POLL_CTRL`
6. `acm_port_shutdown()` — restart bulk-IN polling after port close when `ALWAYS_POLL_CTRL`

`acm_submit_read_urb()` is a no-op for URBs already in flight (it checks
`read_urbs_free` bits), so these calls are safe at any point and do not
conflict with normal TTY operation. With both patches applied, the firmware
receives continuous activity on both EP 0x82 and EP 0x81 at all times,
permanently suppressing both watchdogs.

### Kernel Fix Install

Follow the **Step 1 — Download the Kernel Source** instructions in Part 2 below
to extract the source files and set up `~/kernel-src`. In addition to the HID
driver files, extract the USB class driver files:

```bash
cd ~/kernel-src
KVER=$(ls ../linux-*.tar.xz | grep -oP 'linux-\K[0-9.]+(?=\.tar)')
tar xf ../linux-${KVER}.tar.xz --strip-components=4 \
    linux-${KVER}/drivers/usb/class/cdc-acm.c \
    linux-${KVER}/drivers/usb/class/cdc-acm.h
```

The `Makefile` in `~/kernel-src` builds both modules:
```makefile
obj-m := hid-multitouch.o cdc-acm.o
```

Apply, build, and install:

```bash
cd ~/kernel-src
cp ~/projects/yoga9ibook/scripts/0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch .
cp ~/projects/yoga9ibook/scripts/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch .
patch -p4 < 0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch
patch -p4 < 0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch

# Build against the running kernel's headers
make -C /usr/src/kernels/$(uname -r) M=$(pwd) modules

# Install to updates/ so depmod prefers our version over the stock copy
zstd -f -19 cdc-acm.ko -o cdc-acm.ko.zst
sudo install -d /lib/modules/$(uname -r)/updates
sudo cp cdc-acm.ko.zst /lib/modules/$(uname -r)/updates/
sudo depmod -a

# Reload without rebooting
sudo modprobe -r cdc_acm && sudo modprobe cdc_acm
# Verify:
dmesg | grep ttyACM   # should show: cdc_acm 3-6:1.0: ttyACM0: USB ACM device
```

### Userspace Fallback (deprecated — do not use with cdc-acm patch)

Before the cdc-acm patch was identified, a udev rule + Python script was
developed to send CDC `SET_LINE_CODING` and `SET_CONTROL_LINE_STATE` directly
via the `USBDEVFS_CONTROL` ioctl.

> **This script must NOT be used alongside the cdc-acm patch.**
>
> With both active, the script races against `cdc_acm` for control of EP0 at
> probe time.  A known bug in the script's REMOVE handler (the lock-key lookup
> reads sysfs for the newly-enumerated device rather than the removed one,
> causing the new device's lock file to be deleted) allows a second CDC init
> attempt to proceed.  The resulting control request collision corrupts the
> firmware's contact buffer and creates the persistent ghost contact described
> above.  The udev rule (`99-ingenic-touch-init.rules`) must remain disabled
> (or not installed) when the cdc-acm patch is present.

The script is retained in the repository as documentation and as a fallback
for kernels that cannot carry the cdc-acm patch.

The script uses `ENV{ID_VENDOR_ID}` and `ENV{ID_MODEL_ID}` rather than
`ATTRS{idVendor}` because `ATTRS{}` walks the sysfs ancestor chain independently
for each attribute and can silently match against the USB hub (`idVendor=1d6b`)
instead of the device.

**Files:**
- `scripts/ingenic-touch-init.py` — sends CDC `SET_LINE_CODING` (115200 baud)
  and `SET_CONTROL_LINE_STATE` (DTR=1, RTS=1) via `USBDEVFS_CONTROL` ioctl
- `scripts/99-ingenic-touch-init.rules` — udev rule firing on any hidraw ADD
  for `17EF:6161`; lock mechanism ensures init is sent exactly once per
  enumeration

**Install (fallback only — requires cdc-acm patch to be absent):**
```bash
sudo cp ingenic-touch-init.py /usr/local/sbin/
sudo chmod +x /usr/local/sbin/ingenic-touch-init.py
sudo cp 99-ingenic-touch-init.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

### Files

- `scripts/0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch`
  — Kernel patch for `drivers/usb/class/cdc-acm.{c,h}` (VENDOR_CLASS_DATA_IFACE + ALWAYS_POLL_CTRL); **merged** as f58752ebcb35
- `scripts/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch`
  — Kernel patch for `drivers/usb/class/cdc-acm.c` (bulk-IN polling for ALWAYS_POLL_CTRL); depends on 0004
- `scripts/v1-0005-USB-cdc-acm-start-bulk-IN-polling-when-ALWAYS_POLL_CTRL-is-set.patch`
  — Upstream submission (git format-patch, 8bit transfer encoding; submitted 2026-05-15)
- `scripts/cdc-acm.c` — Patched source file (0004 + 0005 applied) for reference / rebuild
- `scripts/ingenic-touch-init.py` — userspace CDC init fallback
- `scripts/99-ingenic-touch-init.rules` — udev rule for fallback script

### Upstream Submission

**Patch 0002** submitted 2026-04-02 to linux-usb@vger.kernel.org.
Maintainers: Oliver Neukum <oneukum@suse.com>, Greg Kroah-Hartman <gregkh@linuxfoundation.org>
Submission: https://lore.kernel.org/linux-usb/20260402182950.389016-1-carvsdriver@gmail.com/

**Accepted** into Greg Kroah-Hartman's `usb-next` tree on 2026-04-13.
**Merged to Linus's mainline tree** on 2026-04-19 via `usb-7.1-rc1` pull; will ship in kernel 7.1.
The commit also carries `Cc: stable@kernel.org` so stable backports (6.12.y, 6.6.y, etc.) are expected.
Commit: https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f58752ebcb35e156c85cd1a82d6579c7af3b9023

**Patch 0005** (bulk-IN fix) submitted 2026-05-15 to linux-usb@vger.kernel.org.
Message-ID: <20260515141940.751397-1-carvsdriver@gmail.com>
Depends on patch 0004 (f58752ebcb35) and Wentao Guan's pending BIT-collision fix.

**Accepted** into Greg Kroah-Hartman's `usb-testing` branch 2026-05-22.
Will move to `usb-next` after testing; expect in linux-next within 24 hours.

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

The correct fix is a report descriptor fixup in `mt_report_fixup()` in
`drivers/hid/hid-multitouch.c`.  Rather than scattering device-specific
guards throughout the driver, the fixup rewrites the descriptor in memory
before the HID core parses it, eliminating all three root causes at source:

**Step 1 — Remove the HID_DG_TOUCHPAD application collection**

Walk HID short items from the `{ 0x05, 0x0d, 0x09, 0x05, 0xa1, 0x01 }`
header to the matching End Collection, then close the gap with `memmove`.
This eliminates all three BUTTONPAD heuristics and the feature reports
inside the collection in one operation.

**Step 2 — Neutralize Win8 compliance blob GET_REPORT triggers**

Change Usage Page `0xff00` to `0x0f00` so the `case 0xff0000c5` branch in
`mt_feature_mapping()` is not reached and no `GET_REPORT` is issued at
probe.  These requests hit the firmware's CDC-ACM init window (~1.18 s
after enumeration) and trigger resets.

**Step 3 — Neutralize Contact Count Max GET_REPORT triggers**

Change usage `0x55` (HID_DG_CONTACTMAX) to `0x00` so `mt_feature_mapping()`
skips the GET_REPORT.  Set `maxcontacts = 10` in the `MT_CLS_YOGABOOK9I`
class entry so the driver uses the correct limit without querying the
device.

**Step 4 — Neutralize Device Configuration SET_REPORT triggers (except Input Mode)**

Change usages `0x57` (Surface Switch) and `0x58` (Button Switch) in the
Device Configuration collection to `0x00` so `mt_set_modes()` does not
issue `HID_REQ_SET_REPORT` for these on every input-device open/close.
Without this, the repeated control requests hit the firmware's CDC-ACM init
window and trigger resets, appearing as stuck touch state in KWin.

Input Mode (`0x52`) is intentionally **left intact**.  The single
`HID_REQ_SET_REPORT` sent by `mt_set_modes()` at probe time flushes the
firmware's contact buffer and clears a persistent ghost contact (see
*Ghost Contact* below).  By probe time the `cdc-acm` driver has already
satisfied the CDC-ACM init watchdog (~130 ms after enumeration), so this
one request arrives safely after the reset window has closed.

**Step 5 — Add MT_QUIRK_NOT_SEEN_MEANS_UP to the class definition**

`MT_QUIRK_NOT_SEEN_MEANS_UP` sets `INPUT_MT_DROP_UNUSED` on the multitouch
input, causing the kernel to synthesize a lift event for any contact not
present in the current frame.  This prevents stale slots from lingering if
the firmware omits a contact from a report without first clearing TipSwitch.

### Ghost Contact

After each USB enumeration the firmware leaves a **persistent ghost contact**
in its internal contact buffer: contact ID 2 at fixed coordinates
(approximately x=10093, y=13758 in raw HID units), with TipSwitch always
asserted and no tip-off transition.  This occupies a multitouch slot
permanently and prevents KWin from seeing a clean finger-lift on the real
finger, causing stuck touch state.

The ghost is cleared by setting Input Mode via `HID_REQ_SET_REPORT` (the
`mt_set_modes()` probe call for usage 0x52).  This is why Step 4 of the
descriptor fixup leaves usage 0x52 intact — the one-time SET_REPORT at
probe reliably flushes the firmware buffer.

The ghost is stored in firmware RAM only: it does not survive a full power
cycle (reboot) and is cleared within ~200 ms of probe by the Input Mode
SET_REPORT.  It is not present if the firmware's CDC-ACM init sequence is
disrupted during enumeration (e.g., by a race in a userspace CDC init script
sending control requests while the firmware is still initialising).

### Stale-Slot Ghost Contacts

After the misclassification fix, repeated multi-finger gestures (3+ fingers,
lift, repeat) produce ghost contacts on the top screen.  The firmware never
clears TipSwitch in slots that are no longer active: each HID report may
contain up to 10 slots with TipSwitch=1, but only the first ContactCount of
those represent real contacts.  The remaining slots retain TipSwitch=1 at
last-known positions indefinitely.

Raw HID capture confirms: across a 60-second capture with repeated
multi-finger gestures, 90% of frames had more TipSwitch=1 slots than the
reported ContactCount.  ContactCount was always accurate.

Fix: add `MT_QUIRK_CONTACT_CNT_ACCURATE` to the `MT_CLS_YOGABOOK9I` class.
The driver stops processing slots once ContactCount contacts have been
consumed, discarding the stale entries per HID specification section 17.
`MT_QUIRK_NOT_SEEN_MEANS_UP` (already in the class) ensures slots skipped
by this guard are released via `INPUT_MT_DROP_UNUSED` at frame sync.

Submitted 2026-05-14 to linux-input@vger.kernel.org as a follow-up to v2;
awaiting review.

### Result

After applying the kernel patch and the ghost contact fix:
- `props=0x02` = `INPUT_PROP_DIRECT` only (no BUTTONPAD, no POINTER)
- libinput correctly identifies both screens as `cap:t` (touch, direct)
- KDE/Wayland responds to touch on both displays
- On-screen keyboard appears on touch as expected
- Initial ghost contact cleared at probe by Input Mode SET_REPORT; no
  stuck-touch state on normal use
- Stale-slot ghost contacts suppressed by `MT_QUIRK_CONTACT_CNT_ACCURATE`;
  no phantom touches after repeated multi-finger gestures

### Files

- `scripts/v2-0001-HID-multitouch-Fix-Yoga-Book-9-14IAH10-touchscreen-m.patch`
  — Kernel patch (v2) for `drivers/hid/hid-multitouch.c`: descriptor fixup
  (removes HID_DG_TOUCHPAD collection, neutralizes Win8 blob / CONTACTMAX /
  SURFACESWITCH / BUTTONSWITCH feature reports, keeps INPUTMODE for ghost
  contact clearing, sets `maxcontacts = 10`, adds `MT_QUIRK_NOT_SEEN_MEANS_UP`)
- `scripts/v1-0001-HID-multitouch-Honor-ContactCount-for-Yoga-Book-9-to-suppress-ghost-contacts.patch`
  — Kernel patch for `drivers/hid/hid-multitouch.c`: adds
  `MT_QUIRK_CONTACT_CNT_ACCURATE` to suppress stale-slot ghost contacts;
  depends on v2 misclassification fix
- `scripts/hid-multitouch.c` — Patched source file for reference / direct use
- `scripts/0010-INGENIC__Gadget-touchscreen.bpf.c` — HID-BPF program
  (alternative to kernel patch; patches `BTN_LEFT` offsets in the descriptor)

### Upstream Submission

v1 submitted 2026-04-02. Rejected by Benjamin Tissoires: v1 used per-callsite
`MT_QUIRK_YOGABOOK9I` guards; maintainer requested a clean report descriptor
fixup instead.

v2 submitted 2026-04-13. Implements the descriptor fixup approach as requested:
`mt_yogabook9_fixup()` called from `mt_report_fixup()` drops the HID_DG_TOUCHPAD
collection, neutralizes Win8 blob / ContactMax / SurfaceSwitch / ButtonSwitch
GET/SET_REPORT triggers, and retains Input Mode for ghost contact clearing.
**Applied** to hid/for-next by Jiri Kosina 2026-05-12.

Ghost contact patch (v1) submitted 2026-05-14 as a follow-up; depends on v2.

Maintainers: Jiri Kosina <jikos@kernel.org>, Benjamin Tissoires <bentiss@kernel.org>
v1: https://lore.kernel.org/linux-input/20260402182937.388847-1-carvsdriver@gmail.com/
v2: https://lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/
Ghost contact patch: submitted 2026-05-14 to linux-input@vger.kernel.org
Message-ID: <CALPvRORBFHpbos=_xpBVchK-oSZF9EnY6n5-sAQGr=qiL13FbQ@mail.gmail.com>

Stale-slots fix: v1 submitted 2026-05-15, v2 submitted 2026-05-22 (restructured
contact_count block per bentiss review; adds prev_scantime guard).
v1 Message-ID: <20260515175253.873796-1-carvsdriver@gmail.com>
v2 Message-ID: <20260522111527.69428-1-carvsdriver@gmail.com>
Note: v2 subject sent as "[PATCH 2/5]" due to embedded Subject: header; threading
is correct (In-Reply-To v1).

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
cp ~/projects/yoga9ibook/scripts/v2-0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen-m.patch .
patch -p3 < v2-0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen-m.patch

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

## Part 4: Keyboard Dock Detection

### Discovery

The Yoga Book 9 ships with a detachable Bluetooth keyboard that magnetically
attaches to the bottom (secondary) screen in one of two positions: top half or
bottom half. The keyboard position determines the effective screen layout and
whether the device is in "tablet mode" (keyboard detached) or "laptop mode"
(keyboard present).

Without a driver, `SW_TABLET_MODE` is never reported and no sysfs attribute
exposes the dock state. KDE Plasma and screen-rotation daemons rely on
`SW_TABLET_MODE` to decide whether to show the on-screen keyboard and what
screen orientation to apply.

ACPI tracing revealed that the EC tracks attachment state in a 2-bit field
called `BKBD` on the WM10 ACPI device (`_UID "GMZN"`), and signals changes via
WMI notify 0xEB. The embedded BMOF data (WQDD, 20705 bytes, decoded with
`bmfdec`) documents two relevant WMI interfaces:

- **LENOVO_BTKBD_EVENT** (event GUID `806BD2A2-177B-481D-BFB5-3BA0BB4A2285`):
  `WmiDataId(1) uint32 Status` — the ACPI `_WED(0xEB)` method returns `EC.BKBD`
  directly as an integer. No separate query needed in the notify path.

- **LENOVO_FEATURE_STATUS_DATA** (block GUID `E7F300FA-21CD-4003-ADAC-2696135982E6`):
  returns an 8-byte buffer `{uint32 IDs=0x00060000, uint32 Status=BKBD}`.
  Used on probe and resume to read the initial dock state.

### BKBD Encoding

| Value | Meaning |
|-------|---------|
| 0 | Keyboard detached — `SW_TABLET_MODE=1` |
| 1 | Keyboard docked on top half of bottom screen — `SW_TABLET_MODE=0` |
| 2 | Keyboard docked on bottom half of bottom screen — `SW_TABLET_MODE=0` |
| 3 | Reserved (not observed in practice) |

### Kernel Driver

The `lenovo-yb9-kbdock` driver registers two WMI drivers:

- **Event driver** — bound to LENOVO_BTKBD_EVENT GUID; owns the input device
  (`SW_TABLET_MODE`) and the sysfs attribute. Receives BKBD directly in the
  notify callback's event data integer.
- **Block driver** — bound to LENOVO_FEATURE_STATUS_DATA GUID; provides
  `wmidev_block_query()` access for probe-time and resume-time state reads.

Either driver can probe first. Both probe callbacks check whether the other has
already probed and fire the initial BKBD read only when both are ready (mutex
protected). State is re-read on resume from suspend or hibernation.

The sysfs attribute `keyboard_position` performs a live query on every read;
it does not cache the last-reported value.

### Kernel Module Build

The driver is not yet upstream. Build out-of-tree against the running kernel:

```bash
cd ~/projects/yoga9ibook

# Build
make -C /lib/modules/$(uname -r)/build M=$(pwd)/scripts \
    KBUILD_EXTRA_SYMBOLS=$(pwd)/scripts/Module.symvers \
    obj-m=lenovo-yb9-kbdock.o

# Install to updates/ so it takes precedence if upstreamed later
sudo install -m 644 scripts/lenovo-yb9-kbdock.ko \
    /lib/modules/$(uname -r)/updates/
sudo depmod -a

# Load
sudo modprobe lenovo-yb9-kbdock
```

Or load directly without installing:

```bash
sudo insmod scripts/lenovo-yb9-kbdock.ko
```

### Verify

```bash
# Check both WMI drivers bound
ls /sys/bus/wmi/drivers/ | grep yb9

# Read current dock position (0=detached, 1=top-half, 2=bottom-half)
cat /sys/bus/wmi/drivers/lenovo-yb9-kbdock/*/keyboard_position

# Check SW_TABLET_MODE (1=detached/tablet, 0=docked/laptop)
evtest /dev/input/by-id/*yoga-book*
# or
cat /sys/class/input/*/device/name | grep -i "yoga book 9 keyboard"
```

### Upstream Submission

Submitted to `platform-driver-x86@vger.kernel.org` as part of
`drivers/platform/x86/lenovo/`.

v4 Message-ID: `<20260521144034.282419-1-carvsdriver@gmail.com>`
v5 Message-ID: `<20260527122701.242907-1-carvsdriver@gmail.com>`

### Files

- `scripts/lenovo-yb9-kbdock.c` — v5 driver source (two WMI drivers)

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
