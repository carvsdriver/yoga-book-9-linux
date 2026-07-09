# Lenovo Yoga Book 9 14IAH10 — Linux Setup Guide
> Fedora 43 · KDE Plasma 6 · Wayland · Dual boot with Windows

This guide covers a complete Linux setup for the Lenovo Yoga Book 9 14IAH10,
including installation, bootloader configuration, and all hardware fixes
discovered through testing.

This guide will work with or without dual boot.

> **Dual boot users:** You will need a physical keyboard and mouse until Bluetooth is configured in [Step 7](#markdown-header-bluetooth-dual-boot-sync).

This guide is based on personal testing. Open an issue if you run into problems not covered here; pull requests for improvements are welcome.

---

## Table of Contents

1. [Hardware Overview](#markdown-header-hardware-overview)
2. [Known Issues](#markdown-header-known-issues)
3. [TODO](#markdown-header-todo)
4. [Installing Fedora](#markdown-header-installing-fedora)
5. [Upgrading the Kernel](#markdown-header-upgrading-the-kernel)
6. [Installing rEFInd](#markdown-header-installing-refind)
7. [Installing Packages](#markdown-header-installing-packages)
8. [Bluetooth Dual Boot Sync](#markdown-header-bluetooth-dual-boot-sync) *(optional)*
9. [Enabling the Touchscreen](#markdown-header-enabling-the-touchscreen) — Bug 1 (USB reset), Bug 2 (clickpad), Bug 2b (stale MT slots), Bug 2c (ghost contacts), Bug 3 (OSK freeze)
10. [Keyboard Dock Detection](#markdown-header-keyboard-dock-detection)
11. [Fixing Suspend & Wake](#markdown-header-fixing-suspend-wake)
12. [Display Configuration](#markdown-header-display-configuration)
13. [Screen Rotation](#markdown-header-screen-rotation)
14. [Facial Recognition Login](#markdown-header-facial-recognition-login)
15. [Cleanup](#markdown-header-cleanup)
16. [File Reference](#markdown-header-file-reference)

---

## Hardware Overview

| Component | Details |
|-----------|---------|
| Model | Lenovo Yoga Book 9 14IAH10 (83KJ) |
| Displays | Dual 2880×1800 @ 120Hz (eDP-1 top, eDP-2 bottom) |
| Touch | INGENIC USB HID controller (17EF:6161) |
| Keyboard | Yoga Book 9 Bluetooth keyboard |
| Mouse | Yoga Slim Mouse (hardware switch for two device pairing) |
| Sensors | Dual ISH accelerometers, ambient light sensor |
| Boot | UEFI, rEFInd → GRUB → kernel |

---

## Known Issues

[![Open Issues](https://img.shields.io/bitbucket/issues/carvsdriver/lenovoyoga9ibook.svg)](https://bitbucket.org/carvsdriver/lenovoyoga9ibook/issues)

### Bluetooth power-off at KDE session start

`kdeconnectd` powers down the Bluetooth adapter approximately 30 seconds
after login. Re-enabling Bluetooth from the system tray restores full
function. No permanent fix found yet — under investigation.

### Duplicate login screen at boot

SDDM shows the login greeter on both screens simultaneously at boot.
Once logged in, the correct single-screen layout is restored. This is a
KWin/SDDM initialization limitation with no clean fix.

### Occasional freeze on wake

A rare full system freeze can occur shortly after waking from suspend,
requiring a hard reboot. This is an Intel Lunar Lake power management bug
affecting several models. It occurs more frequently under high load.

### Bluetooth on wake

Bluetooth occasionally enters a broken state after suspend/wake. A reboot
fixes it. No permanent workaround found yet.

---

## TODO

1. Fingerprint reader (`17ef:f006` "Idea5003") — no Linux driver available yet.
2. Secure Boot — MOK enrollment seems to require a specific sequence at reboot. Work in progress.
3. Bluetooth power-off by `kdeconnectd` at session start — permanent fix under investigation.

---

## Installing Fedora

### 1. Prepare BIOS

1. Boot into Windows and run `shutdown /s /t 0` for a full shutdown (not fast startup)
2. Power on and press `F2` to enter BIOS
3. Disable **Secure Boot**
4. Set **Boot Mode** to UEFI
5. Disable **Fast Boot**
6. Save and exit

### 2. Create Installation Media

Download the [Fedora KDE Spin](https://fedoraproject.org/spins/kde/) ISO and write it to a USB drive:

```bash
# On Linux
sudo dd if=Fedora-KDE-Live-x86_64-43.iso of=/dev/sdX bs=4M status=progress
```

Or use [Fedora Media Writer](https://flathub.org/apps/org.fedoraproject.MediaWriter) on Windows.

### 3. Boot and Install

1. Insert USB and power on, press `F12` for boot menu
2. Select the USB drive
3. Choose **Try or Install Fedora**
4. In the installer, select **Custom Partitioning**

### 4. Partition Layout (Dual Boot)

> ⚠️ Do not delete the existing Windows EFI partition (`/dev/nvme0n1p1`)

Recommended layout alongside Windows:

| Partition | Size | Filesystem | Mount |
|-----------|------|------------|-------|
| EFI (existing Windows) | 260MB | FAT32 | `/boot/efi` |
| `/boot` | 1GB | ext4 | `/boot` |
| `/` (root) | 60GB+ | btrfs | `/` |
| swap | 16GB | swap | — |

5. Complete installation and reboot

### 5. Post-Install Kernel Parameters

After first boot, edit GRUB to fix ACPI issues:

```bash
sudo nano /etc/default/grub
```

Change `GRUB_CMDLINE_LINUX` to:

```
GRUB_CMDLINE_LINUX="reboot=acpi rhgb quiet video=eDP-1:panel_orientation=upside_down"
```

- **`reboot=acpi`** — required for clean shutdown/reboot on this hardware
- **`video=eDP-1:panel_orientation=upside_down`** — tells the DRM subsystem that
  the top screen (eDP-1) is physically mounted upside-down. Plymouth and the
  early boot framebuffer display correctly as a result. KWin reads but does not
  use this property for its own rotation logic, so the screen rotation service
  requires no changes.

Rebuild GRUB:

```bash
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
```

> ⚠️ Do **not** add `acpi=noirq` — it breaks suspend/wake.

---

## Upgrading the Kernel

Before doing anything else after first boot, upgrade to the latest available kernel. Several of the hardware patches in this guide have already merged to mainline or staging trees — a newer Fedora kernel means fewer out-of-tree modules to build and maintain.

```bash
sudo dnf upgrade kernel
reboot
```

After rebooting, confirm the new version is running:

```bash
uname -r
```

The patch rebuild script (`kernel/rebuild-patches.sh`) automatically detects which patches are already present in the running kernel and skips them.

> **Note:** The cdc-acm USB fix (patch 0004) merged in kernel 7.1. If `uname -r` shows 7.1 or later, that patch is already built in — the script will skip it automatically.

---

## Installing rEFInd

rEFInd provides a graphical boot menu that auto-detects Linux and Windows
without manual configuration.

Using rEFInd will give you a graphical boot menu that works with the touch
screen. This is rather important since you won't be able to use bluetooth
during boot for the keyboard or mouse otherwise (at least not that I have
discovered yet).

### 1. Install rEFInd from Fedora

```bash
sudo dnf install rEFInd
sudo refind-install
```

### 2. Configure Boot Options

rEFInd reads kernel parameters from `/boot/refind_linux.conf`:

```bash
sudo nano /boot/refind_linux.conf
```

Set contents to:

```
"Boot with standard options"  "root=UUID=<your-uuid> ro rootflags=subvol=root reboot=acpi rhgb quiet"
"Boot to single-user mode"    "root=UUID=<your-uuid> ro rootflags=subvol=root reboot=acpi rhgb quiet single"
"Boot with minimal options"   "ro root=/dev/nvme0n1p6"
```

Replace `<your-uuid>` with your root partition UUID:

```bash
sudo blkid | grep btrfs
```

> **Note:** rEFInd on this machine boots through `shimx64.efi → grubx64.efi → kernel`.
> The actual kernel parameters are controlled by `/etc/default/grub`, not `refind_linux.conf`.
> Always rebuild GRUB after changing kernel parameters.

---

## Installing Packages

After Fedora and rEFInd are set up, run the included package install script
to add everything needed for this hardware beyond the base KDE spin:

```bash
chmod +x install-packages.sh
sudo bash install-packages.sh
```

The script installs packages in these groups:

| Group | What it installs |
|-------|-----------------|
| Bluetooth tools | `hivex`, `python3-hivex`, `chntpw` — needed for dual boot BT key sync |
| Sensor support | `iio-sensor-proxy` — needed for screen rotation |
| Display & input | `xinput`, `kscreen` |
| Filesystem tools | `ntfs-3g`, `btrfs-progs`, `exfatprogs`, `nvme-cli`, `kde-partitionmanager`, and others |
| Network tools | `bind-utils`, `nmap-ncat`, `mtr`, `rsync`, `openssh`, and others |
| System utilities | `powertop`, `tlp`, `thermald`, `fwupd`, `efibootmgr`, and others |
| Audio | `alsa-sof-firmware`, `alsa-ucm`, `pipewire-*`, `wireplumber`, `pavucontrol` |

After the script completes:

```bash
# Enable power management
sudo systemctl enable --now tlp
sudo systemctl enable --now thermald
```

> **Note:** The base Fedora KDE spin already includes plasma-desktop, kwin,
> dolphin, firefox, NetworkManager, pipewire, sddm, and all core KDE apps.
> This script only adds what's missing for this specific hardware.

---

## Bluetooth Dual Boot Sync

> **Optional** — only needed if dual booting with Windows and sharing Bluetooth devices.
>
> The Yoga Slim Mouse has a hardware pairing switch and does not need this fix —
> use the switch to toggle between Windows and Linux pairings.
> Only the **Yoga Book 9 Bluetooth keyboard** requires key syncing.

### How it works

When you pair a Bluetooth device in Windows, it generates a pairing key.
When you pair the same device in Linux, a different key is generated.
Each time you switch OS, the device needs to be re-paired.

The fix: pair in both OSes once, then copy Windows' key into Linux so both
OSes share the same key. Windows must always be the source of truth since
devices store Windows' key and Linux will accept it, but not vice versa.

### Prerequisites

```bash
sudo dnf install hivex python3-hivex
```

### Mouse Pairing

1. **Boot into Windows** pair the mouse and note the position of the switch.
2. **Boot into Linux** change the switch to the opposite position and pair the mouse.

### Pairing Order

1. **Remove Pairing From Windows**
2. **Boot into Linux** and pair the keyboard there.
3. **Boot into Windows** and pair the keyboard there.
4. **Boot into Linux** — keyboard will no longer be paired. Do **not** remove the broken pairing yet.
3. **Run the extraction script** (below) to copy Windows' key into Linux.
4. **Restart Bluetooth** — the keyboard should connect without re-pairing.

The only thing you'll have to do between reboots is flip the switch under the mouse.

### The Script

Save `btreg.py` to `~/setup/btreg.py` and run:

```bash
sudo python3 ~/setup/btreg.py
```

The script will:
- Auto-discover and mount the Windows NTFS partition (read-only)
- Extract all Bluetooth pairing keys from the Windows registry
- Print the exact values to update in each Linux device info file
- Unmount and clean up automatically

### Applying the Keys

For each device shown in the output, edit its Linux info file:

```bash
sudo nano /var/lib/bluetooth/<adapter-mac>/<device-mac>/info
```

Update the `[LongTermKey]` or `[PeripheralLongTermKey]` section with the values
from the script output. Do not change the key value in any other sections.

Restart Bluetooth:

```bash
sudo systemctl restart bluetooth
```

### MAC Address Mismatch

BLE devices use rotating MAC addresses and may pair under a different MAC
in each OS. If the device MAC in Windows doesn't match Linux:

```bash
# Copy the Linux pairing to the Windows MAC directory
sudo cp -r /var/lib/bluetooth/<adapter>/<linux-mac> \
           /var/lib/bluetooth/<adapter>/<windows-mac>

# Update the key in the new directory
sudo nano /var/lib/bluetooth/<adapter>/<windows-mac>/info

# Remove the old stale pairing
sudo rm -rf /var/lib/bluetooth/<adapter>/<linux-mac>

sudo systemctl restart bluetooth
```

You may have to run the above fully logged into a shell as sudo:

```bash
sudo -i
```

---

## Enabling the Touchscreen

Touch works on both displays after fixing three separate bugs. Run
`kernel/rebuild-patches.sh` to build and install all patches automatically.
Full technical details, background, and investigation notes are in
[README_Touch.md](README_Touch.md).

### Bug 1: USB Reset Loop

The INGENIC controller resets continuously because `cdc-acm` rejects the device
at probe and leaves the notification endpoint unpolled. A second ~55-second
watchdog fires when the bulk-IN endpoint goes unread.

Patches: **`kernel/patches/0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch`**
and **`kernel/patches/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch`**

> **Upstream (0004):** Merged 2026-04-19; ships in kernel 7.1.
> Commit: [f58752ebcb35](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f58752ebcb35e156c85cd1a82d6579c7af3b9023)
>
> **Upstream (0005):** Merged to usb-next 2026-05-27 (Greg KH); will ship in next major release.

> **Note:** A udev/Python fallback (`99-ingenic-touch-init.rules` +
> `ingenic-touch-init.py`) is retained for reference only. Do not install it
> alongside the cdc-acm patch — a race in the REMOVE handler corrupts the
> firmware contact buffer.

### Bug 2: Touch Misclassified as Clickpad

`hid-multitouch` sets `INPUT_PROP_BUTTONPAD` due to firmware descriptor quirks.
Fixed by a descriptor fixup in `mt_report_fixup()` that removes the TOUCHPAD
collection and neutralizes problematic SET/GET_REPORT triggers.

Patch: **`kernel/patches/0001-HID-multitouch-Fix-Yoga-Book-9-14IAH10-touchscreen-m.patch`**

> **Upstream:** Applied to hid/for-next 2026-05-12 by Jiri Kosina; expected in
> the next merge window.
> v2: [lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/](https://lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/)

### Bug 2b: Stale MT Slots on All-Fingers-Up

The firmware sends `HID_DG_CONTACTCOUNT=0` at all-fingers-up, leaving kernel MT
slots active with stale tracking IDs until the next touch. Fixed in
`mt_touch_report()`.

Patch: **`kernel/patches/0002-HID-multitouch-Fix-stale-MT-slots-when-contact-count-drops-to-zero.patch`**

> **Upstream:** v1 submitted 2026-05-15; v2 submitted 2026-05-22 (restructured per bentiss review); awaiting review.
> v2: [lore.kernel.org/linux-input/20260522111527.69428-1-carvsdriver@gmail.com/](https://lore.kernel.org/linux-input/20260522111527.69428-1-carvsdriver@gmail.com/)

### Bug 2c: Ghost Contacts from Stale Firmware Slots

Firmware slots beyond ContactCount retain `TipSwitch=1` indefinitely, producing
ghost contacts on repeated multi-finger gestures. Fixed by adding
`MT_QUIRK_CONTACT_CNT_ACCURATE` to `MT_CLS_YOGABOOK9I`.

Patch: **`kernel/patches/0003-HID-multitouch-Suppress-cycling-ghost-contacts-for-Yoga-Book-9.patch`**

> **Upstream:** Applied to hid/for-next 2026-06-10 by Jiri Kosina.
> v1: [lore.kernel.org/linux-input/CALPvRORBFHpbos=_xpBVchK-oSZF9EnY6n5-sAQGr=qiL13FbQ@mail.gmail.com/](https://lore.kernel.org/linux-input/CALPvRORBFHpbos=_xpBVchK-oSZF9EnY6n5-sAQGr=qiL13FbQ@mail.gmail.com/)

### Bug 3: Emulated Touchpad Causes On-Screen Keyboard Freezes

The INGENIC device exposes an emulated touchpad node that fires duplicate
mouse-click events alongside touchscreen events, stealing focus from the
on-screen keyboard. A udev rule tells libinput to ignore it:

```bash
sudo cp touch/91-ingenic-emulated-touchpad.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input --action=add
```

Verify:

```bash
sudo libinput list-devices | grep -A4 "Emulated Touchpad"
# Should not appear — libinput ignores it after the rule takes effect
```

### Touch-to-Display Mapping and Stylus Routing

Copy the KWin input mapping to your config and log out/in:

```bash
cp setup/kcminputrc ~/.config/kcminputrc
```

This maps both touchscreens and both stylus inputs to the correct output:

- **Touchscreen Top** → eDP-1
- **Touchscreen Bottom** → eDP-2
- **Stylus Top** → eDP-1 (with 180° calibration matrix for the inverted panel)
- **Stylus Bottom** → eDP-2

KWin automatically applies a 180° calibration to Touchscreen Top because it is
mapped to eDP-1, a Rotated180 output. No additional udev calibration rule is
needed for the top touchscreen. Stylus Top requires an explicit calibration
matrix in kcminputrc because KWin does not auto-calibrate tablet/stylus devices.

### Verify

```bash
# Props should be 2 (INPUT_PROP_DIRECT) on both touchscreens
for d in /sys/class/input/event*/device/name; do
    name=$(cat $d 2>/dev/null)
    echo "$name" | grep -q "Touchscreen" || continue
    event=$(echo $d | sed 's|/sys/class/input/\(event[0-9]*\)/.*|\1|')
    echo "$event ($(cat /sys/class/input/$event/device/properties)): $name"
done
```

### Handling Kernel Updates

The built `.ko.zst` modules are version-specific — they only load on the exact
kernel they were compiled against. After any kernel update you must rebuild and
reinstall before the new kernel is usable with touch.

**Workflow for a kernel update:**

```bash
sudo dnf upgrade kernel
reboot                          # boot into the new kernel first
uname -r                        # confirm you're on the new version
bash ~/projects/yoga9ibook/kernel/rebuild-patches.sh
```

> **Important:** Run `rebuild-patches.sh` *after* rebooting into the new kernel,
> not before. The script builds against `uname -r`; running it on the old kernel
> installs modules under the old version path, which the new kernel will not see.

The script caches the source RPM and tarball by kernel version under
`~/kernel-src-rpms/`, so switching back to an older kernel and rebuilding
again is cheap.

**When a patch reaches mainline**, the script skips it automatically. Patch 0004
is already handled this way (the script greps for `ALWAYS_POLL_CTRL` in the
extracted source and skips if present). Once the remaining patches ship in a
stable kernel, no rebuild is needed for those modules — the stock kernel module
will be correct and the script will become a no-op.

**Current patch / kernel status:**

| Patch | Module | Merged in | Action needed on DNF update |
|-------|--------|-----------|------------------------------|
| 0001 hid-multitouch descriptor fixup | `hid-multitouch` | **mainline** (merged 2026-05-28) | skipped automatically once kernel ships |
| 0002 stale MT slots fix | `hid-multitouch` | submitted 2026-05-22; awaiting review | rebuild |
| 0003 ghost contacts fix | `hid-multitouch` | hid/for-next (applied 2026-06-10) | rebuild until kernel ships |
| 0004 cdc-acm INGENIC quirk | `cdc-acm` | kernel 7.1 | skipped automatically on 7.1+ |
| 0005 cdc-acm bulk-IN polling | `cdc-acm` | usb-next (merged 2026-05-27) | rebuild until kernel ships |
| 0006 yb9-kbdock dock driver | `yb9-kbdock` | v12 submitted 2026-07-08 — [lore](https://lore.kernel.org/all/20260708150909.23404-3-carvsdriver@gmail.com/) | rebuild until merged |
| 0007 lenovo-ymc suppress probe | `lenovo-ymc` | v12 submitted 2026-07-08 — [lore](https://lore.kernel.org/all/20260708150909.23404-2-carvsdriver@gmail.com/) | skipped automatically once merged |

---

## Keyboard Dock Detection

The Yoga Book 9 Bluetooth keyboard magnetically attaches to the bottom screen
in one of two positions.  The EC tracks attachment state in a 2-bit field
(`BKBD`) and signals changes via WMI event 0xEB on the WM10 ACPI device.

| BKBD value | Physical state |
|-----------|----------------|
| 0 | Keyboard detached |
| 1 | Keyboard docked on top half of bottom screen |
| 2 | Keyboard docked on bottom half of bottom screen |

A kernel driver (`lenovo-yb9-kbdock`) handles this:

- Registers as a WMI event driver — autoloads via udev at boot
- Queries initial state at probe time
- Reports `SW_TABLET_MODE=0` (laptop) when keyboard is docked in either
  position, `SW_TABLET_MODE=1` (tablet) when detached
- Exposes raw BKBD value at
  `/sys/bus/wmi/devices/806BD2A2-177B-481D-BFB5-3BA0BB4A2285-11/keyboard_position`

### Build and Install

The easiest way is the rebuild script, which builds and installs all kernel
patches (including this driver) in one step:

```bash
cd ~/projects/yoga9ibook/scripts
bash rebuild-patches.sh
```

To build and install the driver on its own:

```bash
# 1. Install build prerequisites
sudo dnf install kernel-devel-$(uname -r) rpm-build zstd

# 2. Set up an out-of-tree build directory
mkdir -p ~/kernel-src
cp ~/projects/yoga9ibook/kernel/sources/lenovo-yb9-kbdock.c ~/kernel-src/yb9-kbdock.c
echo 'obj-m := yb9-kbdock.o' > ~/kernel-src/Makefile

# 3. Build
make -C /usr/src/kernels/$(uname -r) M=~/kernel-src modules

# 4. Install
zstd -f -19 ~/kernel-src/yb9-kbdock.ko -o ~/kernel-src/yb9-kbdock.ko.zst
sudo install -d /lib/modules/$(uname -r)/extra
sudo cp ~/kernel-src/yb9-kbdock.ko.zst /lib/modules/$(uname -r)/extra/
sudo depmod -a
```

Load without rebooting:

```bash
sudo modprobe yb9_kbdock
```

The module autoloads via udev (`alias wmi:806BD2A2-177B-481D-BFB5-3BA0BB4A2285`).
No `modules-load.d` entry is needed.

### Verify

```bash
# Current keyboard position
cat /sys/bus/wmi/devices/806BD2A2-177B-481D-BFB5-3BA0BB4A2285-11/keyboard_position

# Watch SW_TABLET_MODE events (find event node first)
grep -r "Yoga Book 9 keyboard" /sys/class/input/*/name
sudo evtest /dev/input/eventN
```

> **Upstream:** v12 2-patch series submitted 2026-07-08, awaiting review.
> Cover: [lore.kernel.org/all/20260708150909.23404-1-carvsdriver@gmail.com/](https://lore.kernel.org/all/20260708150909.23404-1-carvsdriver@gmail.com/)

---

## Fixing Suspend & Wake

### Problem

The default Fedora install (and common advice) adds `acpi=noirq` to kernel
parameters to fix shutdown issues. This parameter disables ACPI interrupt
routing and breaks suspend/wake.

### Fix 1: Remove acpi=noirq

```bash
sudo nano /etc/default/grub
```

Ensure `GRUB_CMDLINE_LINUX` contains `reboot=acpi` and does **not** contain
`acpi=noirq`:

```
GRUB_CMDLINE_LINUX="reboot=acpi rhgb quiet"
```

Rebuild GRUB:

```bash
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
```

### Fix 2: Disable XHCI wakeup

The INGENIC USB controller can prevent clean suspend. Disable it as a wakeup source:

```bash
sudo nano /etc/udev/rules.d/99-wakeup-disable.rules
```

```
# Disable XHCI wakeup - prevents suspend issues on Yoga Book 9i
ACTION=="add", SUBSYSTEM=="pci", KERNELS=="0000:00:14.0", ATTR{power/wakeup}="disabled"

# Prevent INGENIC controller from waking system from suspend
ATTRS{name}=="INGENIC Gadget Serial and keyboard*", ATTR{power/wakeup}="disabled"
```

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Verify

```bash
cat /proc/cmdline              # should not contain acpi=noirq
cat /proc/acpi/wakeup | grep XHCI   # should show *disabled
```

---

## Display Configuration

### Screen Layout

The Yoga Book 9i has two identical 2880×1800 displays:

- **eDP-1** — top screen, physically mounted inverted (rotation = inverted)
- **eDP-2** — bottom screen, primary display (rotation = normal)

### KDE Display Setup

In **System Settings → Display & Monitor**:

- Set eDP-2 as **primary**
- Arrange eDP-1 above eDP-2
- Scale both to **175%** (or 1.6× via kscreen-doctor)
- Set both to **120Hz**

### SDDM Login Screen Configuration

Copy KDE's display config to SDDM so the login and lock screens use the
correct layout:

```bash
sudo mkdir -p /var/lib/sddm/.local/share/kscreen/control/configs
sudo cp ~/.local/share/kscreen/control/configs/* \
        /var/lib/sddm/.local/share/kscreen/control/configs/
sudo chown -R sddm:sddm /var/lib/sddm/.local/
```

Create `/etc/sddm.conf.d/display.conf`:

```ini
[General]
DisplayServer=wayland

[Wayland]
EnableHiDPI=true
```

### Accelerometer / Sensor Mount Matrix

The Yoga Book 9 has two ISH accelerometers sharing the same HID modalias, which means
hwdb cannot apply different matrices to each. A udev rules file is required instead —
it matches on `DEVPATH`, which includes the stable HID collection index (`.12` / `.13`).

```bash
sudo cp 61-sensor-yogabook9.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=iio
sudo systemctl restart iio-sensor-proxy
```

This sets the correct matrix (`-1,0,0; 0,1,0; 0,0,1` — negate X only) for both
accelerometers. See `rotation-README.md` for background on why hwdb cannot be used.

---

## Screen Rotation

Both screens rotate together automatically in all orientations. See `rotation-README.md`
for full technical background.

### How it works

`yoga9-rotate.py` is an event-driven Python daemon that:
- Subscribes to `iio-sensor-proxy` via D-Bus for `AccelerometerOrientation` events
- Polls both accelerometer Y-axes directly from sysfs every 100ms to detect tent mode
- Calls `kscreen-doctor` to set rotation and position on both displays
- Debounces changes by 500ms to absorb sensor noise

No patched `iio-sensor-proxy` binary is required.

### Install

First install the udev rules (see [Accelerometer / Sensor Mount Matrix](#markdown-header-accelerometer-sensor-mount-matrix) above), then:

```bash
# Polkit rule — lets the system service claim the accelerometer
sudo cp 51-sensor-proxy-yoga9.rules /etc/polkit-1/rules.d/

# Daemon
sudo cp yoga9-rotate.py /usr/local/bin/yoga9-rotate.py
sudo chmod 755 /usr/local/bin/yoga9-rotate.py

# Service (edit User= and XDG_RUNTIME_DIR= to match your username if not pickles)
sudo cp screen-rotate.service /etc/systemd/system/screen-rotate.service
sudo systemctl daemon-reload
sudo systemctl enable --now screen-rotate.service
```

In **System Settings → Display & Monitor**, disable **Auto-rotate** for both screens
(the service handles rotation instead).

### Rotation Mapping

| Physical orientation | eDP-1 (top, inverted mount) | eDP-2 (bottom) |
|---|---|---|
| Landscape normal | inverted | none |
| Landscape upside-down | none | inverted |
| Portrait, right edge up | left | right |
| Portrait, left edge up | right | left |
| Tent mode | none (mirrored at 0,0) | none |

### Verify

```bash
systemctl status screen-rotate.service
journalctl -u screen-rotate.service -f
```

---

## Facial Recognition Login

The Yoga Book 9i has an IR camera (`/dev/video2`) that works with
[Howdy](https://github.com/boltgolt/howdy) for Windows Hello-style facial
authentication on login, lock screen, and sudo.

> ⚠️ Howdy is convenient, not highly secure. A photo of your face could
> potentially unlock it. Always keep password authentication as a fallback.

### The Dependency Problem

Howdy on Fedora 43 requires `python3-dlib` which is not packaged for
Python 3.14. The `principis/howdy-beta` COPR also fails for the same reason.
The workaround is to use the `starfish/howdy-beta` COPR which bundles all
dependencies, and to build `python3-dlib` as a local RPM first.

### 1. Build python3-dlib

Install build dependencies:

```bash
sudo dnf install -y rpm-build rpmdevtools spectool \
    boost-devel cmake cmake-rpm-macros pybind11-devel \
    gcc-c++ gcc-gfortran fftw-devel flexiblas-devel \
    ffmpeg-free-devel libpng-devel libjpeg-devel \
    sqlite-devel libX11-devel libjxl-devel \
    python3-devel pyproject-rpm-macros

rpmdev-setuptree
```

Create the spec file by copying `dlib.spec` from this repo to `~/rpmbuild/SPECS/dlib.spec`:

```bash
cp dlib.spec ~/rpmbuild/SPECS/dlib.spec
```

Download the source and build:

```bash
spectool -g -R ~/rpmbuild/SPECS/dlib.spec
rpmbuild -ba ~/rpmbuild/SPECS/dlib.spec
```

Install the built RPMs:

```bash
sudo dnf install -y \
    ~/rpmbuild/RPMS/x86_64/dlib-19.24.6-1.fc43.x86_64.rpm \
    ~/rpmbuild/RPMS/x86_64/dlib-devel-19.24.6-1.fc43.x86_64.rpm \
    ~/rpmbuild/RPMS/x86_64/python3-dlib-19.24.6-1.fc43.x86_64.rpm
```

Verify:

```bash
python3 -c "import dlib; print(dlib.__version__)"
```

> **Note:** The unsigned RPMs are contained in this repo as a reference. These should be useable,
> but I recommend that you roll your own as instructed just in case there are variances
> on your machine (which there shouldn't be).

### 2. Install Howdy

```bash
sudo dnf copr enable starfish/howdy-beta
sudo dnf install howdy
```

### 3. Configure the IR Camera

```bash
sudo howdy config
```

Find `device_path` and set it to:

```
device_path = /dev/video2
```

### 4. Add Face Models

```bash
sudo howdy add
```

Look straight into the top camera. Add multiple models at different
angles and distances for better reliability:

```bash
# Add more variants
sudo howdy add   # slightly left
sudo howdy add   # slightly right
sudo howdy add   # further away

# List all models
sudo howdy list

# Remove a bad model by ID
sudo howdy remove <id>
```

### 5. Configure PAM

Add `auth sufficient pam_howdy.so` as the **first line** of each PAM file:

```bash
# sudo
sudo nano /etc/pam.d/sudo

# Login screen
sudo nano /etc/pam.d/sddm

# Lock screen
sudo nano /etc/pam.d/kde
sudo nano /etc/pam.d/kscreensaver
```

Each file should have this as the first line:

```
auth sufficient pam_howdy.so
```

### 6. Test

```bash
# Test face recognition
sudo howdy test

# Test sudo
sudo ls

# Test lock screen
loginctl lock-session
```

---

## Cleanup

After completing the facial recognition setup, remove the build tools and
artifacts used to compile `python3-dlib`. A convenience script is included
in the repo to do this in one step:

```bash
chmod +x RPMCleanup.sh
./RPMCleanup.sh
```

This removes all build dependencies (~500 MiB), cleans up the RPM build
directories, and purges the pip cache. The built RPMs and spec file are
kept so you can reinstall `python3-dlib` without a full rebuild if needed.

> **Note:** The RPMs at `~/rpmbuild/RPMS/x86_64/` are kept intentionally.
> To reinstall without rebuilding:
> ```bash
> sudo dnf install ~/rpmbuild/RPMS/x86_64/python3-dlib-*.rpm
> ```

---

## File Reference

### Scripts

| File | Location | Purpose |
|------|----------|---------|
| `install-packages.sh` | repo root | Install all required packages after base Fedora setup |
| `btreg.py` | `~/setup/btreg.py` | Extract Windows BT keys for dual boot sync |
| `yoga9-rotate.py` | `/usr/local/bin/yoga9-rotate.py` | Dual-screen rotation daemon |
| `make-srpm.sh` | run in place | Build a SRPM for COPR upload |
| `yoga-book9-rotation.spec` | — | RPM spec for packaging `yoga9-rotate.py` |
| `dlib.spec` | repo root | RPM spec for building python3-dlib on Fedora 43 |
| `RPMCleanup.sh` | repo root | Remove build dependencies after howdy setup |
| `touch/ingenic-touch-init.py` | `/usr/local/sbin/ingenic-touch-init.py` | CDC init fallback (deprecated — do not use with cdc-acm patch; see README_Touch.md) |
| `kernel/rebuild-patches.sh` | run in place | Rebuild and reinstall both kernel patches |

### Systemd Services

| File | Location | Purpose |
|------|----------|---------|
| `screen-rotate.service` | `/etc/systemd/system/screen-rotate.service` | Runs `yoga9-rotate.py` at login (system service, User=pickles) |
| `yoga9-rotate.service` | `/usr/lib/systemd/user/` | User service variant for RPM/fresh installs |

### udev Rules

| File | Purpose |
|------|---------|
| `61-sensor-yogabook9.rules` → `/etc/udev/rules.d/` | Accelerometer mount matrix fix (replaces broken hwdb approach) |
| `51-sensor-proxy-yoga9.rules` → `/etc/polkit-1/rules.d/` | Polkit grant for system service to claim accelerometer |
| `touch/99-ingenic-touch-init.rules` → `/etc/udev/rules.d/` | udev rule for CDC init fallback (deprecated — do not install with cdc-acm patch) |
| `touch/91-ingenic-emulated-touchpad.rules` → `/etc/udev/rules.d/` | Hide emulated touchpad from libinput (fixes OSK freeze) |
| `/etc/udev/rules.d/99-wakeup-disable.rules` | Disable XHCI/INGENIC wakeup sources |

### Kernel Patches and Drivers

| File | Purpose |
|------|---------|
| `kernel/upstream/v2-0001-HID-multitouch-Fix-Yoga-Book-9-14IAH10-touchscreen-m.patch` | Fix `INPUT_PROP_BUTTONPAD` misclassification for INGENIC touchscreen (**merged** hid/for-next 2026-05-12) |
| `kernel/patches/0002-HID-multitouch-Fix-stale-MT-slots-when-contact-count-drops-to-zero.patch` | hid-multitouch: release stale MT slots when firmware sends `CONTACTCOUNT=0` on all-fingers-up |
| `kernel/upstream/v1-0001-HID-multitouch-Honor-ContactCount-for-Yoga-Book-9-to-suppress-ghost-contacts.patch` | hid-multitouch: `MT_QUIRK_CONTACT_CNT_ACCURATE` to suppress stale-slot ghost contacts (**applied** hid/for-next 2026-06-10) |
| `kernel/sources/hid-multitouch.c` | Patched hid-multitouch source for reference / rebuild |
| `kernel/patches/0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch` | cdc-acm: bind INGENIC USB interface, keep notification endpoint polled (**merged** as f58752ebcb35, kernel 7.1) |
| `kernel/patches/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch` | cdc-acm: keep bulk-IN endpoint drained to suppress ~55 s firmware watchdog (**merged** usb-next 2026-05-27) |
| `kernel/sources/cdc-acm.c` | Patched cdc-acm source (0004 + 0005 applied) for reference / rebuild |
| `kernel/sources/lenovo-yb9-kbdock.c` | WMI driver source: keyboard dock detection via BKBD EC field; reports `SW_TABLET_MODE` (v12, awaiting upstream review) |
| `kernel/patches/0006-platform-x86-lenovo-add-Yoga-Book-9-keyboard-dock-driver.patch` | platform/x86/lenovo: yb9-kbdock driver (v12) |
| `kernel/patches/0007-platform-x86-lenovo-lenovo-ymc-Skip-Yoga-Book-9.patch` | lenovo-ymc: DMI blocklist to prevent duplicate `SW_TABLET_MODE` node on Yoga Book 9 (v12) |

### HID-BPF (Alternative to Kernel Patch)

| File | Purpose |
|------|---------|
| `touch/0010-INGENIC__Gadget-touchscreen.bpf.c` | BPF descriptor fixup — patches `BTN_LEFT` offsets at runtime without replacing the kernel module |

### Configuration Files

| File | Purpose |
|------|---------|
| `/etc/default/grub` | Kernel parameters (`reboot=acpi`) |
| `/etc/sddm.conf.d/display.conf` | SDDM Wayland display config |
| `/var/lib/sddm/.local/share/kscreen/` | SDDM screen layout |
| `~/.local/share/kscreen/` | KDE screen layout |
| `setup/kcminputrc` → `~/.config/kcminputrc` | Touch-to-display output mapping for KWin |
