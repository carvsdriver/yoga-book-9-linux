# Keyboard Dock Detection

## Summary

The keyboard only docks on the bottom screen, in one of two positions
(top half or bottom half).  Attachment state is tracked by the Embedded
Controller in a 2-bit field (`BKBD`) and signalled to the OS via a WMI
event on the WM10 ACPI device.  A kernel driver (`lenovo-yb9-kbdock`)
handles the event and reports `SW_TABLET_MODE` to userspace.

## BKBD Values

| Value | Physical state |
|-------|----------------|
| 0 | Keyboard detached |
| 1 | Keyboard docked on top half of bottom screen |
| 2 | Keyboard docked on bottom half of bottom screen |
| 3 | Not observed |

## How It Works

### EC field

`BKBD` is a 2-bit field at byte offset `0x23` of EC RAM (bits 4–5).
It is defined in the ACPI DSDT inside the `EC0` Embedded Controller device
(`\_SB.PC00.LPCB.EC0`):

```
Offset (0x23),
    ,   2,       // bits 0-1
PELF,   1,       // bit 2
    ,   1,       // bit 3
BKBD,   2,       // bits 4-5  ← keyboard attachment state
    ,   1,
U7U9,   1,
```

### Event path

When the keyboard is docked or undocked:

1. EC fires query `_QB0` (`0xB0`)
2. `_QB0` calls `Notify(WM10, 0xEB)`
3. WM10 is a PNP0C14 WMI device (`_UID "GMZN"`) — the WMI subsystem receives
   the notification and calls any registered handler
4. `_WED(0xEB)` returns the current `BKBD` value as event data

### WMI query (current state)

`WQAF` reads `BKBD` on demand and returns an 8-byte buffer:

```
bytes [0..3]  LFID = 0x00060000  (field identifier)
bytes [4..7]  BKBD value (0–3)
```

This is used at driver probe time to report the initial state without waiting
for an event.

### WMI GUIDs (from DSDT `_WDG` buffer, WM10 device)

| Role | GUID | Object / Notify ID |
|------|------|--------------------|
| Event | `806BD2A2-177B-481D-BFB5-3BA0BB4A2285` | Notify `0xEB` |
| Query | `E7F300FA-21CD-4003-ADAC-2696135982E6` | Object `AF` (WQAF) |

## Driver

**Source:** `scripts/lenovo-yb9-kbdock.c`

**Build and install:**

```bash
cd ~/drivers/lenovo-ymc-yb9
make
sudo cp lenovo-yb9-kbdock.ko \
    /lib/modules/$(uname -r)/kernel/drivers/platform/x86/lenovo/
sudo depmod -a
```

The module carries `alias wmi:806BD2A2-177B-481D-BFB5-3BA0BB4A2285` so udev
autoloads it at boot when the WMI device is enumerated. No `modules-load.d`
entry is needed.

**SW_TABLET_MODE mapping:**

| BKBD | SW_TABLET_MODE | Meaning |
|------|---------------|---------|
| 1, 2 | 0 | Keyboard docked (either position) — laptop mode |
| 0 | 1 | Keyboard detached — tablet mode |

**Raw position sysfs:**

```bash
cat /sys/bus/wmi/devices/806BD2A2-177B-481D-BFB5-3BA0BB4A2285-11/keyboard_position
# → "0 (detached)" | "1 (top-half)" | "2 (bottom-half)"
```

**Monitoring events:**

```bash
# ACPI event fires on dock/undock:
acpi_listen
# → wmi PNP0C14:01 000000eb 00000000

# SW_TABLET_MODE transitions (find the event node first):
grep -r "Yoga Book 9 keyboard" /sys/class/input/*/name
sudo evtest /dev/input/eventN
```

> **Note:** WMI events without a bound driver do not generate udev events.
> `udevadm monitor` will not show dock/undock activity. Use `acpi_listen` for
> raw event monitoring.

## What Was Ruled Out

The following were investigated before the ACPI/WMI path was found:

| Signal | Result |
|--------|--------|
| `SW_TABLET_MODE` from `lenovo_ymc` (hinge angle) | No change on dock/undock |
| udev input events | No events |
| INGENIC USB hidraw interrupt reports (iface 2, 4, 5, 6) | No reports |
| Bluetooth keyboard hidraw interrupt reports | No reports |
| ISH accelerometers (X/Y/Z axes) | No change on dock/undock |
| Ambient light sensor | Constant |
| Bluetooth RSSI | Not accessible for connected devices via BlueZ DBus |
| Touchscreen contact (keyboard rubber feet) | Not conductive; no touch events |
| `hid-sensor-custom-intel-hinge` module | Module loads but no matching platform device on this hardware |

## Upstream Status

Staged locally as of 2026-04-21. Not yet submitted.
