# Lenovo Yoga Book 9 14IAH10 — Linux Setup Guide
> Fedora 43 · KDE Plasma 6 · Wayland · Dual boot with Windows

This guide covers a complete Linux setup for the Lenovo Yoga Book 9 14IAH10,
including installation, bootloader configuration, and all hardware fixes
discovered through testing.

This guide will work with or without dual boot.

IMPORTANT NOTE:

If you are dual boot, you will need to use a physical keyboard and
mouse until you get Bluetooth sorted out in Step 7.

DISCLAIMER

I did this out of sheer boredom and the desire to share knowledge. While this
should work, you need to be prepared to handle any oddities or nuances along
the way. If anything else crops up during daily use, I will update this guide.

Please feel free to open an issue if you find any problems specific to this
guide. Submit pull requests for recommended changes.

---

## Table of Contents

1. [Hardware Overview](#markdown-header-hardware-overview)
2. [Known Issues](#markdown-header-known-issues)
3. [TODO](#markdown-header-todo)
4. [Installing Fedora](#markdown-header-installing-fedora)
5. [Installing rEFInd](#markdown-header-installing-refind)
6. [Installing Packages](#markdown-header-installing-packages)
7. [Bluetooth Dual Boot Sync](#markdown-header-bluetooth-dual-boot-sync) *(optional)*
8. [Enabling the Touchscreen](#markdown-header-enabling-the-touchscreen) — Bug 1 (USB reset), Bug 2 (clickpad), Bug 2b (stale MT slots), Bug 2c (ghost contacts), Bug 3 (OSK freeze)
9. [Keyboard Dock Detection](#markdown-header-keyboard-dock-detection)
10. [Fixing Suspend & Wake](#markdown-header-fixing-suspend-wake)
11. [Display Configuration](#markdown-header-display-configuration)
12. [Screen Rotation](#markdown-header-screen-rotation)
13. [Facial Recognition Login](#markdown-header-facial-recognition-login)
14. [Cleanup](#markdown-header-cleanup)
15. [File Reference](#markdown-header-file-reference)

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

1. Fingerprint reader (`17ef:f006` "Idea5003") — no Linux driver available as of March 2026.
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
4. **Boot into Linux** keyboard will no longer be paried. Do **not** remove the broken pairing yet.
3. **Run the extraction script** (below) to copy Windows' key into Linux.
4. **Restart Bluetooth** — the keyboard should connect without re-pairing.

The only thing you'll have to do between reboots is flip the switch under the mouse.

### The Script

Save `btreg.py` to `~/scripts/btreg.py` and run:

```bash
sudo python3 ~/scripts/btreg.py
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

Touch works on both displays after fixing three separate bugs. Full technical
details, background, and the USBPcap investigation are in
[README_Touch.md](README_Touch.md).

### Bug 1: USB Reset Loop

The INGENIC controller resets continuously because Linux's `cdc-acm` driver
rejects the device at probe: the CDC data interface (interface 1) declares
vendor-specific class (`0xFF`) instead of `USB_CLASS_CDC_DATA`, causing
`-EINVAL` and leaving the notification endpoint (EP 0x82) unpolled. Without
a consumer on EP 0x82, the firmware enters a reset loop indefinitely.

Fixed with two `cdc-acm` kernel patches:

- **`scripts/0004-USB-CDC-ACM-...patch`** — adds `VENDOR_CLASS_DATA_IFACE` (bypasses
  the interface class check) and `ALWAYS_POLL_CTRL` (keeps EP 0x82 polled at all times).
- **`scripts/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch`** — keeps
  the bulk-IN endpoint (EP 0x81) drained at all times when `ALWAYS_POLL_CTRL` is set.
  The firmware has a second ~55-second watchdog that monitors bulk-IN activity; without
  this patch the device resets every ~55 s whenever no TTY is open.

See [README_Touch.md](README_Touch.md) for full build and install instructions.

> **Upstream (0004):** Merged to mainline 2026-04-19 (via `usb-7.1-rc1` pull); will ship in kernel 7.1.
> Carries `Cc: stable@kernel.org` — stable backports expected.
> Commit: [f58752ebcb35](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f58752ebcb35e156c85cd1a82d6579c7af3b9023)
> Original submission: [lore.kernel.org/linux-usb/20260402182950.389016-1-carvsdriver@gmail.com/](https://lore.kernel.org/linux-usb/20260402182950.389016-1-carvsdriver@gmail.com/)
>
> **Upstream (0005):** Submitted 2026-05-14 to linux-usb@vger.kernel.org; awaiting review.

A udev rule and Python script (`99-ingenic-touch-init.rules` +
`ingenic-touch-init.py`) exist as a fallback for kernels without the cdc-acm
patch.  **Do not install or enable this script alongside the cdc-acm patch.**
A race in the script's REMOVE handler causes a second CDC init attempt on each
re-enumeration, corrupting the firmware contact buffer and creating a persistent
ghost contact.  The script is retained for reference only.

### Bug 2: Touch Misclassified as Clickpad

`hid-multitouch` incorrectly sets `INPUT_PROP_BUTTONPAD` due to three firmware
quirks in the descriptor.  Fixed with a descriptor fixup in `mt_report_fixup()`
and a class definition update:

- Removes the HID_DG_TOUCHPAD application collection (eliminates all three
  BUTTONPAD heuristics)
- Neutralizes Win8 compliance blob and Contact Count Max GET_REPORT triggers
  (prevent firmware resets at probe)
- Neutralizes Surface Switch / Button Switch SET_REPORT triggers (prevent firmware
  resets on every input-device open/close); Input Mode is intentionally kept so
  the probe-time SET_REPORT flushes the firmware's contact buffer and clears a
  persistent ghost contact (cid 2, fixed coordinates, tip always asserted) that
  otherwise causes stuck-touch state in KWin
- Adds `MT_QUIRK_NOT_SEEN_MEANS_UP` to the class so stale multitouch slots are
  released if the firmware omits a contact without a tip-off transition

> **Upstream:** v1 rejected; v2 submitted 2026-04-13 and **applied to hid/for-next**
> 2026-05-12 by Jiri Kosina. Expected in the next merge window.
> v2: [lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/](https://lore.kernel.org/linux-input/20260413125803.46792-1-carvsdriver@gmail.com/)

#### Before You Start: Upgrade to the Target Kernel

The patches are built against the **running** kernel. Upgrade to the latest
kernel and reboot before building so the installed module matches what is
actually running:

```bash
sudo dnf upgrade kernel
reboot
```

After reboot, confirm you are on the expected version:

```bash
uname -r   # e.g. 6.19.10-200.fc43.x86_64
```

If a new kernel arrives later via `dnf upgrade`, you must rebuild and reinstall
both patches against the new kernel before rebooting into it. The installed
`.ko.zst` files are version-specific and will not load under a different kernel.

#### Getting the Kernel Source

```bash
# 1. Install build requirements
sudo dnf install kernel-devel-$(uname -r) rpm-build

# 2. Download the source RPM for the running kernel
sudo dnf download --source kernel-$(uname -r | sed 's/\.[^.]*$//')

# 3. Extract the kernel source tarball
rpm2cpio kernel-*.src.rpm | cpio -idmv '*.tar.xz'

# 4. Set up the build directory
mkdir -p ~/kernel-src
cd ~/kernel-src

# 5. Extract only the two files needed for out-of-tree build
KVER=$(ls ../linux-*.tar.xz | grep -oP 'linux-\K[0-9.]+(?=\.tar)')
tar xf ../linux-${KVER}.tar.xz --strip-components=3 \
    linux-${KVER}/drivers/hid/hid-multitouch.c \
    linux-${KVER}/drivers/hid/hid-ids.h

# 6. Create the out-of-tree module Makefile
echo 'obj-m := hid-multitouch.o' > Makefile
```

#### Apply the Patch and Build

```bash
cd ~/kernel-src
cp ~/projects/yoga9ibook/scripts/v2-0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen-m.patch .
patch -p3 < v2-0001-HID-multitouch-Fix-Yoga-Book-9-touchscreen-m.patch

make -C /usr/src/kernels/$(uname -r) M=$(pwd) modules

# Install
zstd -f -19 hid-multitouch.ko -o hid-multitouch.ko.zst
sudo cp hid-multitouch.ko.zst \
    /lib/modules/$(uname -r)/kernel/drivers/hid/hid-multitouch.ko.zst
sudo depmod -a
```

Reload the module without rebooting:

```bash
sudo rmmod hid_multitouch && sudo modprobe hid_multitouch
```

Or reboot.

#### Alternative: HID-BPF Descriptor Fixup

A HID-BPF program is available as a lighter-weight alternative that patches
the report descriptor at runtime without replacing the kernel module. See
[README_Touch.md](README_Touch.md) for full build and deployment instructions.

```bash
# Quick deploy after building (see README_Touch.md for build steps)
sudo udev-hid-bpf install \
    ~/kernel-src/bpf/0010-INGENIC__Gadget-touchscreen.bpf.o
```

### Bug 2b: Stale MT Slots on All-Fingers-Up

The INGENIC firmware sends `HID_DG_CONTACTCOUNT=0` in the frame immediately
after all fingers lift, rather than simply omitting the frame.  In
`mt_touch_report()`, the existing code only updates `num_expected` when
`contact_count` is non-zero.  With `contact_count=0`, `num_expected` retains
its previous value (e.g. 2 for a two-finger gesture), so the sync check
`num_received >= num_expected` evaluates `0 >= 2` and never fires.
`INPUT_MT_DROP_UNUSED` is never called, leaving kernel MT slots active with
stale tracking IDs until the next touch.  Any userspace consumer that tracks
active-contact transitions — such as a gesture daemon — sees a batch release
of the old contacts alongside the new ones, corrupting session state between
gestures.

Fixed in `mt_touch_report()` by resetting `num_expected` to 0 when
`contact_count` is zero and `num_received` is still 0 (i.e., this is the
first packet of a new frame, not a continuation packet):

```c
else if (app->num_received == 0)
    app->num_expected = 0;
```

With `num_expected=0`, the sync check `0 >= 0` fires immediately and
`input_mt_sync_frame()` releases the stale slots via `INPUT_MT_DROP_UNUSED`.
The `num_received == 0` guard is critical: it excludes continuation packets
in multi-packet frames, which arrive with `num_received > 0`.

Patch: **`scripts/0002-HID-multitouch-Fix-stale-MT-slots-when-contact-count-drops-to-zero.patch`**

> **Upstream:** Not yet submitted (2026-04-27).

The patch is applied automatically by `scripts/rebuild-patches.sh` immediately
after the Bug 2 hid-multitouch descriptor patch.

### Bug 2c: Ghost Contacts from Stale Firmware Slots

After the misclassification fix, repeated multi-finger gestures (3+ fingers,
lift, repeat) produce ghost contacts on the top screen.  The firmware never
clears TipSwitch in slots that are no longer active: each HID report may
contain up to 10 slots with TipSwitch=1, but only the first ContactCount
represent real contacts.  The remaining slots retain TipSwitch=1 at
last-known positions indefinitely.

Raw HID capture confirmed: 90% of frames had more active slots than
ContactCount; ContactCount was always accurate.

Fixed by adding `MT_QUIRK_CONTACT_CNT_ACCURATE` to `MT_CLS_YOGABOOK9I`.
The driver stops processing slots once ContactCount contacts have been
consumed, per HID specification section 17.  `MT_QUIRK_NOT_SEEN_MEANS_UP`
(already in the class) releases skipped slots via `INPUT_MT_DROP_UNUSED`
at frame sync.

Patch: **`scripts/v1-0001-HID-multitouch-Honor-ContactCount-for-Yoga-Book-9-to-suppress-ghost-contacts.patch`**

> **Upstream:** Submitted 2026-05-13 to linux-input@vger.kernel.org; awaiting
> review. Depends on Bug 2 fix (v2) being applied first.

The patch is applied automatically by `scripts/rebuild-patches.sh`.

### Bug 3: Emulated Touchpad Causes On-Screen Keyboard Freezes

The INGENIC composite device exposes a `HID_DG_TOUCHPAD` collection alongside
the two touchscreens. `hid-multitouch` creates a separate input node for it
("Emulated Touchpad") which libinput sees as a pointer device. Every finger tap
fires both a touchscreen event and a duplicate mouse-click event from the
emulated touchpad, stealing focus from the on-screen keyboard.

Fixed with a udev rule that tells libinput to ignore the emulated touchpad node:

```bash
sudo cp scripts/91-ingenic-emulated-touchpad.rules /etc/udev/rules.d/
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
cp scripts/kcminputrc ~/.config/kcminputrc
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
cp ~/projects/yoga9ibook/scripts/lenovo-yb9-kbdock.c ~/kernel-src/yb9-kbdock.c
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

> **Upstream (0005):** `scripts/0005-platform-x86-lenovo-add-Yoga-Book-9-keyboard-dock-driver.patch`
> — full in-tree patch with `Kconfig`/`Makefile` entries; staged locally, not yet submitted.

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

The Yoga Book 9 14IAH10 is not in the default udev hwdb. Add it:

```bash
sudo nano /etc/udev/hwdb.d/61-sensor-yogabook9.hwdb
```

```
# Lenovo Yoga Book 9 14IAH10 accelerometer mount matrix
sensor:modalias:platform:HID-SENSOR-200073:dmi:*:svnLENOVO:pn83KJ:*
 ACCEL_MOUNT_MATRIX=-1, 0, 0; 0, -1, 0; 0, 0, 1
```

```bash
sudo systemd-hwdb update
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=iio
sudo systemctl restart iio-sensor-proxy
```

---

## Screen Rotation

Both screens rotate together in landscape and portrait modes based on the
bottom screen's accelerometer. Screen positions are also updated so the
displays are correctly arranged in both landscape (stacked vertically) and
portrait (side by side) orientations.

### How it works

- A custom shell script polls the raw accelerometer values from both ISH accelerometers
- Tent mode is detected by comparing the Y axis sign of both accelerometers — in tent mode they read opposite signs
- In tent mode both screens mirror at the same position showing identical content
- In all other modes the script calls `kscreen-doctor` to rotate and reposition both displays
- A systemd system service runs the script automatically at boot
- A second systemd system service restarts the rotation service after every
  suspend/resume cycle to clear stale state and let KWin settle
- The script retries `kscreen-doctor` up to 5 times on failure to handle
  KWin settling after resume

### Install

1. Copy `rotate-screens.sh` to `/usr/local/bin/` and make it executable:

```bash
sudo cp rotate-screens.sh /usr/local/bin/rotate-screens.sh
sudo chmod 755 /usr/local/bin/rotate-screens.sh
```

2. Copy both service files to `/etc/systemd/system/`:

```bash
sudo cp screen-rotate.service /etc/systemd/system/screen-rotate.service
sudo cp screen-rotate-resume.service /etc/systemd/system/screen-rotate-resume.service
```

3. Edit the rotation service file and update the `User` field and `XDG_RUNTIME_DIR`
   to match your username:

```bash
sudo nano /etc/systemd/system/screen-rotate.service
```

> **Note:** This service runs as a specific user because `kscreen-doctor`
> needs access to that user's Wayland session. If multiple users need screen
> rotation, a separate service instance is required for each — copy the
> service file with a different name, update the `User` and
> `XDG_RUNTIME_DIR` fields accordingly, and enable each instance
> separately.

4. Enable and start both services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now screen-rotate.service
sudo systemctl enable --now screen-rotate-resume.service
```

5. In **System Settings → Display & Monitor**, disable **Auto-rotate** for both
   screens (the service handles rotation instead)

### Rotation Mapping

| Physical orientation | eDP-1 (top) | eDP-2 (bottom) | Position |
|---------------------|-------------|----------------|----------|
| Landscape (normal) | inverted | none | stacked vertically |
| Landscape (upside down) | none | inverted | stacked vertically |
| Portrait (right) | left | right | side by side |
| Portrait (left) | right | left | side by side |
| Tent mode | none | none | mirrored at 0,0 |

### Verify

```bash
sudo systemctl status screen-rotate.service
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
| `btreg.py` | `~/scripts/btreg.py` | Extract Windows BT keys for dual boot sync |
| `rotate-screens.sh` | `/usr/local/bin/rotate-screens.sh` | Rotate both screens based on accelerometer |
| `dlib.spec` | repo root | RPM spec for building python3-dlib on Fedora 43 |
| `RPMCleanup.sh` | repo root | Remove build dependencies after howdy setup |
| `scripts/ingenic-touch-init.py` | `/usr/local/sbin/ingenic-touch-init.py` | CDC init fallback (deprecated — do not use with cdc-acm patch; see README_Touch.md) |
| `scripts/rebuild-patches.sh` | run in place | Rebuild and reinstall both kernel patches |

### Systemd Services

| File | Location | Purpose |
|------|----------|---------|
| `screen-rotate.service` | `/etc/systemd/system/screen-rotate.service` | Runs rotation script at boot |
| `screen-rotate-resume.service` | `/etc/systemd/system/screen-rotate-resume.service` | Restarts rotation service after suspend/resume |

### udev Rules

| File | Purpose |
|------|---------|
| `scripts/99-ingenic-touch-init.rules` → `/etc/udev/rules.d/` | udev rule for CDC init fallback (deprecated — do not install with cdc-acm patch) |
| `scripts/91-ingenic-emulated-touchpad.rules` → `/etc/udev/rules.d/` | Hide emulated touchpad from libinput (fixes OSK freeze) |
| `/etc/udev/rules.d/99-wakeup-disable.rules` | Disable XHCI/INGENIC wakeup sources |
| `/etc/udev/hwdb.d/61-sensor-yogabook9.hwdb` | Accelerometer mount matrix |

### Kernel Patches and Drivers

| File | Purpose |
|------|---------|
| `scripts/v2-0001-HID-multitouch-Fix-Yoga-Book-9-14IAH10-touchscreen-m.patch` | Fix `INPUT_PROP_BUTTONPAD` misclassification for INGENIC touchscreen (v2; applied hid/for-next 2026-05-12) |
| `scripts/v1-0001-HID-multitouch-Honor-ContactCount-for-Yoga-Book-9-to-suppress-ghost-contacts.patch` | hid-multitouch: `MT_QUIRK_CONTACT_CNT_ACCURATE` to suppress stale-slot ghost contacts (submitted 2026-05-13) |
| `scripts/0002-HID-multitouch-Fix-stale-MT-slots-when-contact-count-drops-to-zero.patch` | hid-multitouch: release stale MT slots when firmware sends `CONTACTCOUNT=0` on all-fingers-up |
| `scripts/hid-multitouch.c` | Patched hid-multitouch source for reference / rebuild |
| `scripts/0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch` | cdc-acm: bind INGENIC USB interface, keep notification endpoint polled (**merged** as f58752ebcb35) |
| `scripts/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch` | cdc-acm: keep bulk-IN endpoint drained to suppress ~55 s firmware watchdog |
| `scripts/v1-0005-USB-cdc-acm-start-bulk-IN-polling-when-ALWAYS_POLL_CTRL-is-set.patch` | cdc-acm bulk-IN patch upstream submission (submitted 2026-05-14) |
| `scripts/cdc-acm.c` | Patched cdc-acm source (0004 + 0005 applied) for reference / rebuild |
| `scripts/lenovo-yb9-kbdock.c` | WMI driver source: keyboard dock detection via BKBD EC field; reports `SW_TABLET_MODE` |
| `scripts/0006-platform-x86-lenovo-add-Yoga-Book-9-keyboard-dock-driver.patch` | platform/x86/lenovo: yb9-kbdock as a proper in-tree driver with Kconfig/Makefile entries (upstream format) |

### HID-BPF (Alternative to Kernel Patch)

| File | Purpose |
|------|---------|
| `scripts/0010-INGENIC__Gadget-touchscreen.bpf.c` | BPF descriptor fixup — patches `BTN_LEFT` offsets at runtime without replacing the kernel module |

### Configuration Files

| File | Purpose |
|------|---------|
| `/etc/default/grub` | Kernel parameters (`reboot=acpi`) |
| `/etc/sddm.conf.d/display.conf` | SDDM Wayland display config |
| `/var/lib/sddm/.local/share/kscreen/` | SDDM screen layout |
| `~/.local/share/kscreen/` | KDE screen layout |
| `scripts/kcminputrc` → `~/.config/kcminputrc` | Touch-to-display output mapping for KWin |
