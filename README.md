# Lenovo Yoga Book 9 14IAH10 — Linux Setup Guide
> Fedora 43 · KDE Plasma 6 · Wayland · Dual boot with Windows

Setup guide for the Lenovo Yoga Book 9 14IAH10 (83KJ). Works with or without dual boot.

> **Dual boot users:** You'll need a physical keyboard and mouse until Bluetooth is configured in [Step 7](#bluetooth-dual-boot-sync).

Open an issue if you run into something not covered here; pull requests welcome.

---

## Table of Contents

1. [Hardware Overview](#hardware-overview)
2. [Known Issues](#known-issues)
3. [Installing Fedora](#installing-fedora)
4. [Upgrading the Kernel](#upgrading-the-kernel)
5. [Installing rEFInd](#installing-refind)
6. [Installing Packages](#installing-packages)
7. [Bluetooth Dual Boot Sync](#bluetooth-dual-boot-sync) *(optional)*
8. [Enabling the Touchscreen](#enabling-the-touchscreen)
9. [Keyboard Dock & On-Screen Touchpad](#keyboard-dock--on-screen-touchpad)
10. [Fixing Suspend & Wake](#fixing-suspend--wake)
11. [Display Configuration](#display-configuration)
12. [Screen Rotation](#screen-rotation)
13. [Facial Recognition Login](#facial-recognition-login)

---

## Hardware Overview

| Component | Details |
|-----------|---------|
| Model | Lenovo Yoga Book 9 14IAH10 (83KJ) |
| Displays | Dual 2880×1800 @ 120Hz (eDP-1 top, eDP-2 bottom) |
| Touch | INGENIC USB HID controller (17EF:6161) |
| Keyboard | Yoga Book 9 Bluetooth keyboard |
| Mouse | Yoga Slim Mouse (hardware switch for two-device pairing) |
| Sensors | Dual ISH accelerometers, ambient light sensor |
| Boot | UEFI, rEFInd → GRUB → kernel |

---

## Known Issues

- **Bluetooth powered off at login** — `kdeconnectd` kills the adapter ~30s after login; re-enable from tray. Under investigation.
- **Duplicate login screen at boot** — SDDM shows on both screens until first login. Known KWin/SDDM limitation.
- **Occasional freeze on wake** — rare Intel Lunar Lake power management bug. Hard reboot required.
- **Bluetooth broken after suspend** — intermittent; reboot to fix.
- **Fingerprint reader** (`17ef:f006`) — no Linux driver available.
- **Secure Boot** — MOK enrollment under investigation.

---

## Installing Fedora

### 1. Prepare BIOS

1. In Windows: `shutdown /s /t 0` (full shutdown, not fast startup)
2. Power on, press `F2` → BIOS
3. Disable **Secure Boot**, disable **Fast Boot**, set Boot Mode to **UEFI**

### 2. Create Installation Media

Download [Fedora KDE Spin](https://fedoraproject.org/spins/kde/). Write to USB:

```bash
sudo dd if=Fedora-KDE-Live-x86_64-43.iso of=/dev/sdX bs=4M status=progress
```

Or use [Fedora Media Writer](https://flathub.org/apps/org.fedoraproject.MediaWriter) on Windows.

### 3. Install

Boot from USB (`F12` for boot menu), choose **Try or Install Fedora**, select **Custom Partitioning**.

**Partition layout (dual boot):**

> ⚠️ Do not delete the existing Windows EFI partition (`/dev/nvme0n1p1`)

| Partition | Size | Filesystem | Mount |
|-----------|------|------------|-------|
| EFI (existing) | 260MB | FAT32 | `/boot/efi` |
| `/boot` | 1GB | ext4 | `/boot` |
| `/` | 60GB+ | btrfs | `/` |
| swap | 16GB | swap | — |

### 4. Kernel Parameters

After first boot, add required parameters:

```bash
sudo nano /etc/default/grub
```

```
GRUB_CMDLINE_LINUX="reboot=acpi rhgb quiet video=eDP-1:panel_orientation=upside_down"
```

- `reboot=acpi` — required for clean shutdown on this hardware
- `video=eDP-1:panel_orientation=upside_down` — fixes Plymouth orientation for the inverted top panel

```bash
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
```

> ⚠️ Do **not** add `acpi=noirq` — it breaks suspend/wake.

---

## Upgrading the Kernel

Upgrade the kernel before doing anything else. Most hardware patches have merged to mainline — a newer kernel means fewer out-of-tree modules.

```bash
sudo dnf upgrade kernel && reboot
```

> **Linux 7.3+ contains every patch in this guide.** On 7.3 or later, no out-of-tree modules are needed.

---

## Installing rEFInd

rEFInd provides a touch-friendly boot menu — important since Bluetooth isn't available at boot.

```bash
sudo dnf install rEFInd
sudo refind-install
```

Configure `/boot/refind_linux.conf`:

```
"Boot with standard options"  "root=UUID=<your-uuid> ro rootflags=subvol=root reboot=acpi rhgb quiet"
```

Get your UUID: `sudo blkid | grep btrfs`

> **Note:** On this machine rEFInd boots through `shimx64.efi → grubx64.efi → kernel`. Kernel parameters are controlled by `/etc/default/grub` — always rebuild GRUB after changing them.

---

## Installing Packages

```bash
chmod +x install-packages.sh
sudo bash install-packages.sh
```

Then enable power management:

```bash
sudo systemctl enable --now tlp thermald
```

---

## Bluetooth Dual Boot Sync

> **Optional** — only needed if dual booting and sharing the Yoga Book 9 Bluetooth keyboard. The Yoga Slim Mouse has a hardware switch and doesn't need this.

Windows and Linux generate separate pairing keys for the same device. The fix copies Windows' key into Linux so both OSes share one key.

**Pairing order (must follow exactly):**

1. Remove keyboard pairing from Windows
2. Boot Linux, pair keyboard
3. Boot Windows, pair keyboard
4. Boot Linux (keyboard won't connect — do not remove the broken pairing)
5. Run the extraction script:

```bash
sudo python3 ~/setup/btreg.py
```

6. For each device in the output, edit its Linux info file and update the `[LongTermKey]` section:

```bash
sudo nano /var/lib/bluetooth/<adapter-mac>/<device-mac>/info
sudo systemctl restart bluetooth
```

**BLE MAC address mismatch** — if the device MAC differs between OSes:

```bash
sudo cp -r /var/lib/bluetooth/<adapter>/<linux-mac> \
           /var/lib/bluetooth/<adapter>/<windows-mac>
sudo nano /var/lib/bluetooth/<adapter>/<windows-mac>/info
sudo rm -rf /var/lib/bluetooth/<adapter>/<linux-mac>
sudo systemctl restart bluetooth
```

---

## Enabling the Touchscreen

Touch requires kernel patches and a udev rule. Run the rebuild script to build and install everything:

```bash
bash ~/projects/yoga9ibook/kernel/rebuild-patches.sh
```

The script detects which patches are already in your kernel and skips them. On Linux 7.3+ it's a no-op — all patches are already built in.

Then install the udev rule to fix the on-screen keyboard:

```bash
sudo cp touch/91-ingenic-emulated-touchpad.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=input --action=add
```

Apply the KWin input mapping (maps each touchscreen and stylus to the correct output):

```bash
cp setup/kcminputrc ~/.config/kcminputrc
```

Then log out and back in.

After a kernel update, reboot into the new kernel first, then re-run `rebuild-patches.sh`.

> See [README_Touch.md](README_Touch.md) for full technical details, bug descriptions, and patch status.

---

## Keyboard Dock & On-Screen Touchpad

The `lenovo-yb9-kbdock` driver detects when the Bluetooth keyboard is magnetically docked. It's built into Linux 7.3+; on earlier kernels `rebuild-patches.sh` builds it automatically.

The on-screen touchpad daemon turns the exposed strip of the bottom screen into a trackpad when the keyboard is docked:

```bash
sudo dnf copr enable carvsdriver/yoga-book-9
sudo dnf install plasma-touchpad yoga-book9-rotation
```

Log out and back in. Configure the touchpad in **System Settings → On-Screen Touchpad**.

> Both packages are in the same COPR — the single `copr enable` covers both.

---

## Fixing Suspend & Wake

Ensure `reboot=acpi` is in `GRUB_CMDLINE_LINUX` and `acpi=noirq` is **not** (see [Installing Fedora](#installing-fedora)).

Disable the INGENIC controller as a wakeup source:

```bash
sudo nano /etc/udev/rules.d/99-wakeup-disable.rules
```

```
ACTION=="add", SUBSYSTEM=="pci", KERNELS=="0000:00:14.0", ATTR{power/wakeup}="disabled"
ATTRS{name}=="INGENIC Gadget Serial and keyboard*", ATTR{power/wakeup}="disabled"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Display Configuration

In **System Settings → Display & Monitor**:

- Set eDP-2 as **primary**
- Arrange eDP-1 above eDP-2
- Scale both to **175%**
- Set both to **120Hz**

Copy the layout to SDDM so the login screen uses the correct configuration:

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

---

## Screen Rotation

Both screens rotate together automatically. The `yoga9-rotate` daemon subscribes to `iio-sensor-proxy` and drives `kscreen-doctor` for synchronized dual-screen rotation and tent mode detection.

```bash
sudo dnf copr enable carvsdriver/yoga-book-9
sudo dnf install yoga-book9-rotation
```

The package installs and auto-enables a systemd user service (`yoga9-rotate.service`) and the udev accelerometer mount matrix fix. Log out and back in for the service to start.

In **System Settings → Display & Monitor**, disable **Auto-rotate** for both screens.

> Source: [github.com/carvsdriver/yoga-book9-rotation](https://github.com/carvsdriver/yoga-book9-rotation)

---

## Facial Recognition Login

The IR camera at `/dev/video2` works with [Howdy](https://github.com/boltgolt/howdy).

> ⚠️ Howdy is convenient but not highly secure. Keep password auth as a fallback.

### 1. Build python3-dlib (required for Fedora 43)

```bash
sudo dnf install -y rpm-build rpmdevtools spectool boost-devel cmake cmake-rpm-macros \
    pybind11-devel gcc-c++ gcc-gfortran fftw-devel flexiblas-devel ffmpeg-free-devel \
    libpng-devel libjpeg-devel sqlite-devel libX11-devel libjxl-devel \
    python3-devel pyproject-rpm-macros
rpmdev-setuptree
cp dlib.spec ~/rpmbuild/SPECS/dlib.spec
spectool -g -R ~/rpmbuild/SPECS/dlib.spec
rpmbuild -ba ~/rpmbuild/SPECS/dlib.spec
sudo dnf install -y ~/rpmbuild/RPMS/x86_64/dlib-*.rpm \
    ~/rpmbuild/RPMS/x86_64/python3-dlib-*.rpm
```

### 2. Install and configure Howdy

```bash
sudo dnf copr enable starfish/howdy-beta
sudo dnf install howdy
sudo howdy config   # set device_path = /dev/video2
sudo howdy add      # enroll face (add several angles)
```

### 3. Enable PAM authentication

Add `auth sufficient pam_howdy.so` as the **first line** of:

```
/etc/pam.d/sudo
/etc/pam.d/sddm
/etc/pam.d/kde
/etc/pam.d/kscreensaver
```

### 4. Clean up build dependencies

```bash
./RPMCleanup.sh
```
