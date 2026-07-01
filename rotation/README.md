# Yoga Book 9 Accelerometer Investigation

## Goal

Implement native Linux screen rotation through the standard stack
(`iio-sensor-proxy` → KDE) so it works on future installs without the
custom `rotate-screens.sh` daemon. This document tracks findings from
Layer 0 investigation.

## Hardware

**Device:** Lenovo Yoga Book 9 14IAH10 (83KJ)
**Sensors:** Two `accel_3d` IIO devices via Intel ISH HID Sensor Hub (8087:0AC2)

Both accelerometers live under the same HID device (`001F:8087:0AC2.0003`),
as two platform children with different HID collection indices:

| IIO device | Platform name | Collection | Physical location |
|---|---|---|---|
| `iio:device2` | `HID-SENSOR-200073.12.auto` | .12 | Top screen section (eDP-1) |
| `iio:device3` | `HID-SENSOR-200073.13.auto` | .13 | Bottom/base section (eDP-2) |

**Physical mapping confirmed by:** raw readings with laptop open at normal
use angle. dev2 shows Y≈−919k, Z≈−416k (angled section = lid). dev3 shows
Y≈−44k, Z≈−999k (near-flat = base on desk).

Both share the same modalias: `platform:HID-SENSOR-200073`. The `.12`/`.13`
collection index is **not** part of the modalias — this is critical for the
hwdb bug described below.

## Current iio-sensor-proxy State

`iio-sensor-proxy` is running and actively using the accelerometers.
Both devices are tagged:

```
IIO_SENSOR_PROXY_TYPE=iio-poll-accel iio-buffer-accel
SYSTEMD_WANTS=iio-sensor-proxy.service
```

iio-sensor-proxy picks the **first** matching IIO device via udev enumeration,
which is `iio:device2` (lower device number = .12.auto = top screen). This is
the correct device to use for rotation.

## The hwdb Bug

`/etc/udev/hwdb.d/61-sensor-yogabook9.hwdb` exists and was written with the
right intent — different matrices for each accel — but has a critical bug:

```
# Entry 1 — labeled "bottom screen"
sensor:modalias:platform:HID-SENSOR-200073:dmi:*:svnLENOVO:pn83KJ:*
 ACCEL_MOUNT_MATRIX=1, 0, 0; 0, 1, 0; 0, 0, 1

# Entry 2 — labeled "top screen"
sensor:modalias:platform:HID-SENSOR-200073:dmi:*:svnLENOVO:pn83KJ:*
 ACCEL_MOUNT_MATRIX=-1, 0, 0; 0, -1, 0; 0, 0, 1
```

**Both entries match both devices** (the modalias is identical for .12 and
.13). The second entry silently overwrites the first for every match.
Result: both accelerometers get `-1, 0, 0; 0, -1, 0; 0, 0, 1`.

**This cannot be fixed in hwdb** — there is no hwdb-compatible match key that
includes the collection index (`.12` vs `.13`). The fix requires a udev
**rules** file (`.rules`) that matches on `DEVPATH`.

Current effective matrix for both devices (confirmed via `udevadm info`):
`ACCEL_MOUNT_MATRIX=-1, 0, 0; 0, -1, 0; 0, 0, 1`

## Orientation Calculation (iio-sensor-proxy algorithm)

iio-sensor-proxy applies the mount matrix to raw values, then uses the
dominant corrected axis to determine orientation:

- `|corrected_y| > |corrected_x|` and `|corrected_y| > threshold`:
  - `corrected_y > 0` → `normal`
  - `corrected_y < 0` → `bottom-up`
- `|corrected_x| > |corrected_y|` and `|corrected_x| > threshold`:
  - `corrected_x > 0` → `right-up`
  - `corrected_x < 0` → `left-up`
- Otherwise → `undefined` (device flat or ambiguous)

## Hardware Test Results

Test run 2026-06-25. 90-second accel log + simultaneous `monitor-sensor`
capture. Device cycled through: laptop open → closed flat → tent mode →
landscape (two directions) → portrait tablet.

Raw log: `/tmp/accel-test-1782401769.log`

**Stable phases identified:**

| Time | dev2 corr (X,Y,Z) | dev3 corr (X,Y,Z) | Physical position | monitor-sensor |
|---|---|---|---|---|
| 11:36:09–14 | Y=+912, Z=−406 | Y=+47, Z=−999 | Laptop open, normal use | "normal" |
| 11:36:21 | Z=+985, Y≈0 | Z=−996, Y≈0 | Lid closed flat, screen face-down | transitioning |
| 11:36:47–53 | Y≈+965 | Y≈−880 | **Tent mode** — OPPOSITE Y SIGNS ✓ | "normal" (blind to tent) |
| 11:37:00–02 | X=+987, Y≈−44 | X=+1013, Y≈+8 | Landscape, right edge up | "right-up" |
| 11:37:08–16 | X=−1020, Y≈+10 | X=−995, Y≈+10 | Landscape, left edge up | "left-up" |
| 11:37:25–29 | Y=−1010 | Y=−975 | **Portrait tablet, top edge up** | **"bottom-up" ← BUG** |

**Critical finding:** holding the device correctly as a portrait tablet (top
screen facing user, top edge up, text right-side-up) causes iio-sensor-proxy
to report `bottom-up`. This is caused by the wrong Y sign in the mount matrix.

**Root cause:**

In portrait tablet top-up orientation: `raw2_y ≈ +1031` (positive).

Current matrix negates Y: `corr_y = −raw_y = −1031` → negative → "bottom-up".

For iio-sensor-proxy to report "normal" in this position, `corr_y` must be
positive. Therefore Y must **not** be negated. X negation is still correct
(verified from landscape data: raw_x≈−961 in right-up position gives
corr_x=+961 → "right-up" ✓).

**Tent mode confirmation:**

At 11:36:47–53: `dev2 raw_y ≈ −974` (negative), `dev3 raw_y ≈ +870`
(positive). Signs are opposite → tent detection algorithm from
`rotate-screens.sh` works correctly. iio-sensor-proxy is blind to this
because it only reads one device.

## Correct Mount Matrix

**Both accelerometers should use: `-1, 0, 0; 0, 1, 0; 0, 0, 1`**

(Negate X only. Do not negate Y. Keep Z unchanged.)

Verification with this matrix:

| Position | raw2_y or raw2_x | corr value | iio-sensor-proxy |
|---|---|---|---|
| Portrait top-up | raw_y = +1031 | corr_y = +1031 | "normal" ✓ |
| Portrait bottom-up | raw_y = −1031 | corr_y = −1031 | "bottom-up" ✓ |
| Landscape right-up | raw_x = −961 | corr_x = +961 | "right-up" ✓ |
| Landscape left-up | raw_x = +1007 | corr_x = −1007 | "left-up" ✓ |
| Tent (dev2 vs dev3) | raw_y signs opposite | still opposite | tent detectable ✓ |

Both `.12` (dev2, top screen) and `.13` (dev3, base) need the same matrix.
Dev3's raw values in the same physical positions match dev2's sign pattern.

## Fix Applied (Layer 1 complete — 2026-06-25)

`/etc/udev/rules.d/61-sensor-yogabook9.rules` installed and verified.
Source copy: `screen-rotate/61-sensor-yogabook9.rules`.

The fix uses a udev **rules** file (not hwdb) so it can match on DEVPATH,
which includes the stable HID collection index. Rules run after the hwdb
import in `60-sensor.rules` and override `ACCEL_MOUNT_MATRIX`.

Applied with:
```
sudo udevadm trigger --action=add --subsystem-match=iio
sudo udevadm settle
sudo systemctl restart iio-sensor-proxy
```

Verified: both `iio:device2` and `iio:device3` show
`ACCEL_MOUNT_MATRIX=-1, 0, 0; 0, 1, 0; 0, 0, 1`. `monitor-sensor`
reports `normal` when device is held as portrait tablet (top edge up). ✓

**Note on laptop-open orientation:** with the correct matrix, the laptop-open
pose (screen angled) reports `bottom-up` (raw_y ≈ −923, corrected y = −923).
This is expected and acceptable — KDE will use `SW_TABLET_MODE=0` from the
kbdock driver to suppress auto-rotation in laptop mode (Layer 4 concern).

## Tent Mode (Layer 2 complete — 2026-06-25)

Tent mode is detected by `yoga9-rotate.py` reading both accelerometer Y-axes directly
from sysfs. No `iio-sensor-proxy` patch is required.

### Detection logic

```
if |dev2_raw_y| > 100000 and |dev3_raw_y| > 100000:
    if sign(dev2_raw_y) != sign(dev3_raw_y):
        tent_mode = true
```

The 100000 raw-unit threshold (≈0.1G) prevents false positives when the device is
near-flat. Since the mount matrix only negates X (`corrected_y = raw_y` for both
accels), the raw values are directly comparable without applying any correction.

### Implementation

The daemon polls every 100ms via `GLib.timeout_add`. Paths are found by enumerating
`/sys/bus/iio/devices/iio:device*` (7 entries, instant) and checking `os.path.realpath()`
for the HID collection suffix `.12.auto` (display) or `.13.auto` (base).

**Important:** `glob('sys/devices/**', recursive=True)` hangs on this hardware — it
traverses the entire sysfs device tree and blocks in some subsystem entries. The IIO
bus symlink approach avoids this entirely.

### Verification

```bash
# Watch the daemon log
journalctl -u screen-rotate.service -f

# Fold the device into tent mode and look for:
# yoga9-rotate INFO: state=tent  output.eDP-1.rotation.none ...
```

Tent mode was physically verified 2026-06-25: both screens go to `none` rotation at
position (0,0) when folded past 180°, returning to `normal` on unfold.
