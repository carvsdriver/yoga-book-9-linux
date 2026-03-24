# Lenovo Yoga Book 9 14IAH10 — Linux Setup Guide
> Fedora 43 · KDE Plasma 6 · Wayland · Dual boot with Windows

This guide covers a complete Linux setup for the Lenovo Yoga Book 9 14IAH10,
including installation, bootloader configuration, and all hardware fixes
discovered through testing.

This guide will work with or without dual boot.

DISCLAIMER

I did this out of sheer boredom and the desire to share knowledge. While this
should work, you need to be prepared to handle any oddities or nuances along
the way. If anything else crops up during daily use, I will update this guide.

Please feel free to open an issue if you find any problems specific to this
guide. Submit pull requests for recommended changes.

---

## Table of Contents

1. [Hardware Overview](#hardware-overview)
2. [Known Issues](#known-issues)
3. [TODO](#todo)
4. [Installing Fedora](#installing-fedora)
5. [Installing rEFInd](#installing-refind)
6. [Installing Packages](#installing-packages)
7. [Bluetooth Dual Boot Sync](#bluetooth-dual-boot-sync) *(optional)*
8. [Disabling the Touchscreen](#disabling-the-touchscreen)
9. [Fixing Suspend & Wake](#fixing-suspend--wake)
10. [Display Configuration](#display-configuration)
11. [Screen Rotation](#screen-rotation)
12. [File Reference](#file-reference)

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

### Touchscreen (unfixable)

The INGENIC USB HID controller resets its USB connection on every touch event.
This is a hardware firmware bug with no Linux fix as of March 2026. The
touchscreen is disabled via udev as a result.

- Tracked at: https://github.com/linuxwacom/libwacom/issues/602

Additionally, this prevents using this as a traditional laptop with the
keyboard sitting on top of the bottom screen. For now, you'll have to use
the oragami kickstand.

### Duplicate login screen at boot

SDDM shows the login greeter on both screens simultaneously at boot.
Once logged in, the correct single-screen layout is restored. This is a
KWin/SDDM initialization limitation with no clean fix.

### Upside-down Plymouth splash

The Plymouth boot splash shows eDP-1 inverted during early boot before
KDE applies its display config. Adding `video=eDP-1:2880x1800@120,rotate=180`
to kernel parameters would fix this but risks interfering with the working
screen rotation service.

### Occasional freeze on wake

A rare full system freeze can occur shortly after waking from suspend,
requiring a hard reboot. This is an Intel Lunar Lake power management bug
affecting several models. It occurs more frequently under high load.

### Bluetooth on wake

Bluetooth occasionally enters a broken state after suspend/wake. A reboot
fixes it. No permanent workaround found yet.

---

## TODO

1. Add tent mode to screen rotation.
2. Add screen duplication to tent mode (if possible -- nice to have).
3. Attempt to add touch to bottom screen to enable laptop mode with keyboard docked.
4. ?????
5. PROFIT!

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
GRUB_CMDLINE_LINUX="reboot=acpi rhgb quiet"
```

Rebuild GRUB:

```bash
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
```

> ⚠️ Do **not** add `acpi=noirq` — it breaks suspend/wake.

---

## Installing rEFInd

rEFInd provides a graphical boot menu that auto-detects Linux and Windows
without manual configuration.

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

### Pairing Order

1. **Pair the keyboard in Windows first**
2. **Boot into Linux** and pair the keyboard there too
3. **Run the extraction script** (below) to copy Windows' key into Linux
4. **Restart Bluetooth** — the keyboard should connect without re-pairing

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

Update the `[LongTermKey]` section with the values from the script output,
then restart Bluetooth:

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

---

## Disabling the Touchscreen

The INGENIC USB HID touch controller (17EF:6161) has a firmware bug on Linux
that causes the entire USB device to disconnect and reconnect on every touch
event, making touch unusable. There is no known fix as of March 2026.

### Disable via udev

```bash
sudo nano /etc/udev/rules.d/99-disable-touch.rules
```

```
# Disable Yoga Book 9i touchscreens and emulated touchpad
ATTRS{name}=="INGENIC Gadget Serial and keyboard Touchscreen Top", ENV{LIBINPUT_IGNORE_DEVICE}="1"
ATTRS{name}=="INGENIC Gadget Serial and keyboard Touchscreen Bottom", ENV{LIBINPUT_IGNORE_DEVICE}="1"
ATTRS{name}=="INGENIC Gadget Serial and keyboard Emulated Touchpad", ENV{LIBINPUT_IGNORE_DEVICE}="1"
```

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Log out and back in to apply.

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
bottom screen's accelerometer (iio:device0).

### How it works

- `iio-sensor-proxy` reads the accelerometer and exposes orientation via DBus
- A custom shell script polls the raw accelerometer values directly
- The script calls `kscreen-doctor` to rotate both displays simultaneously
- A systemd user service runs the script automatically at login

### Install

1. Save `rotate-screens.sh` to `~/scripts/rotate-screens.sh`

2. Make it executable:
```bash
chmod +x ~/scripts/rotate-screens.sh
```

3. Save `screen-rotate.service` to `~/.config/systemd/user/screen-rotate.service`

4. Enable and start:
```bash
systemctl --user daemon-reload
systemctl --user enable screen-rotate.service
systemctl --user start screen-rotate.service
```

5. In **System Settings → Display & Monitor**, disable **Auto-rotate** for both
   screens (the service handles rotation instead)

### Rotation Mapping

| Physical orientation | eDP-1 (top) | eDP-2 (bottom) |
|---------------------|-------------|----------------|
| Landscape (normal) | inverted | none |
| Landscape (upside down) | none | inverted |
| Portrait (right) | left | right |
| Portrait (left) | right | left |

### Verify

```bash
systemctl --user status screen-rotate.service
journalctl --user -u screen-rotate.service -f
```

---

## File Reference

### Scripts

| File | Location | Purpose |
|------|----------|---------|
| `install-packages.sh` | repo root | Install all required packages after base Fedora setup |
| `btreg.py` | `~/scripts/btreg.py` | Extract Windows BT keys for dual boot sync |
| `rotate-screens.sh` | `~/scripts/rotate-screens.sh` | Rotate both screens based on accelerometer |

### Systemd Services

| File | Location | Purpose |
|------|----------|---------|
| `screen-rotate.service` | `~/.config/systemd/user/screen-rotate.service` | Run rotation script at login |

### udev Rules

| File | Purpose |
|------|---------|
| `/etc/udev/rules.d/99-disable-touch.rules` | Disable INGENIC touchscreen |
| `/etc/udev/rules.d/99-wakeup-disable.rules` | Disable XHCI/INGENIC wakeup sources |
| `/etc/udev/hwdb.d/61-sensor-yogabook9.hwdb` | Accelerometer mount matrix |

### Configuration Files

| File | Purpose |
|------|---------|
| `/etc/default/grub` | Kernel parameters (`reboot=acpi`) |
| `/etc/sddm.conf.d/display.conf` | SDDM Wayland display config |
| `/var/lib/sddm/.local/share/kscreen/` | SDDM screen layout |
| `~/.local/share/kscreen/` | KDE screen layout |
