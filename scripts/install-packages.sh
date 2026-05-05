#!/bin/bash
# install-packages.sh
# Post-install package setup for Lenovo Yoga Book 9 14IAH10
# Fedora 43 KDE Spin
#
# Usage: sudo bash install-packages.sh
#
# This script installs packages beyond the base Fedora KDE spin.
# The base KDE spin already includes: plasma-desktop, kwin, konsole,
# dolphin, firefox, NetworkManager, pipewire, sddm, and most KDE apps.

# dnf flags:
#   --skip-unavailable  skip packages not found in repos instead of erroring
#   Already-installed packages are silently skipped by dnf automatically
DNF="dnf install -y --skip-unavailable"

echo "=== Yoga Book 9i Post-Install Package Setup ==="
echo ""

# -------------------------------------------------------
# Bluetooth dual boot sync
# Required for syncing BT pairing keys between Windows/Linux
# -------------------------------------------------------
echo "[1/8] Installing Bluetooth tools..."
$DNF \
    hivex \
    python3-hivex \
    chntpw

# -------------------------------------------------------
# Sensor & rotation support
# Required for accelerometer-based screen rotation
# -------------------------------------------------------
echo "[2/8] Installing sensor support..."
$DNF \
    iio-sensor-proxy

# -------------------------------------------------------
# Display & input tools
# -------------------------------------------------------
echo "[3/8] Installing display and input tools..."
$DNF \
    xinput \
    kscreen

# -------------------------------------------------------
# Filesystem & disk tools
# Useful for dual boot NTFS access and disk management
# -------------------------------------------------------
echo "[4/8] Installing filesystem tools..."
$DNF \
    ntfs-3g \
    ntfsprogs \
    btrfs-progs \
    exfatprogs \
    dosfstools \
    udisks2-btrfs \
    compsize \
    nvme-cli \
    smartmontools \
    parted \
    kde-partitionmanager

# -------------------------------------------------------
# Network tools
# -------------------------------------------------------
echo "[5/8] Installing network tools..."
$DNF \
    bind-utils \
    nmap-ncat \
    traceroute \
    mtr \
    wget2-wget \
    rsync \
    openssh-clients \
    openssh-server

# -------------------------------------------------------
# System utilities
# -------------------------------------------------------
echo "[6/8] Installing system utilities..."
$DNF \
    pciutils \
    usbutils \
    lsof \
    tree \
    dos2unix \
    unzip \
    zip \
    curl \
    powertop \
    tlp \
    thermald \
    fwupd \
    efibootmgr

# -------------------------------------------------------
# Audio
# Required for proper audio on Yoga Book 9i
# -------------------------------------------------------
echo "[7/8] Installing audio packages..."
$DNF \
    alsa-sof-firmware \
    alsa-ucm \
    alsa-utils \
    pipewire-alsa \
    pipewire-pulseaudio \
    pipewire-utils \
    wireplumber \
    pavucontrol

# -------------------------------------------------------
# rEFInd bootloader
# Required if using rEFInd instead of GRUB
# -------------------------------------------------------
echo "[8/8] Installing rEFInd..."
$DNF \
    rEFInd

echo ""
echo "=== Package installation complete ==="

# -------------------------------------------------------
# Kernel patches
# Build and install patched hid-multitouch, cdc-acm, and
# yb9-kbdock modules for the running kernel.
# -------------------------------------------------------
REBUILD="${BASH_SOURCE%/*}/rebuild-patches.sh"
if [ -x "${REBUILD}" ]; then
    echo ""
    echo "[kernel patches] Applying kernel patches..."
    bash "${REBUILD}"
else
    echo ""
    echo "[kernel patches] WARNING: rebuild-patches.sh not found at ${REBUILD}"
    echo "  Run it manually after cloning the yoga9ibook repo."
fi

echo ""
echo "Next steps:"
echo "  1. Run: sudo refind-install    (if using rEFInd)"
echo "  2. Run: sudo tlp start         (enable power management)"
echo "  3. Run: sudo systemctl enable --now thermald"
echo "  4. Follow README.md for hardware-specific configuration"
