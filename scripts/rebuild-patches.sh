#!/usr/bin/env bash
# rebuild-patches.sh — Rebuild and reinstall hid-multitouch, cdc-acm, and
# yb9-kbdock kernel patches for the running kernel.
#
# Patches applied:
#   0001  hid-multitouch  — Yoga Book 9 touchscreen descriptor fixup
#   0002  hid-multitouch  — Fix stale MT slots when contact count drops to zero
#   0003  hid-multitouch  — Suppress cycling ghost contacts (INGENIC firmware bug)
#   0004  cdc-acm         — INGENIC 17EF:6161 quirk (VENDOR_CLASS_DATA_IFACE +
#                           ALWAYS_POLL_CTRL)
#   0005  cdc-acm         — start bulk-IN polling when ALWAYS_POLL_CTRL is set
#   0006  yb9-kbdock      — keyboard dock detection driver (new file; copied
#                           from lenovo-yb9-kbdock.c in this directory)
#
# Usage:
#   cd ~/projects/yoga9ibook/scripts
#   bash rebuild-patches.sh

set -euo pipefail

KVER="$(uname -r)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${HOME}/kernel-src"
RPM_CACHE="${HOME}/kernel-src-rpms"

HID_PATCH="${SCRIPT_DIR}/0001-HID-multitouch-Fix-Yoga-Book-9-14IAH10-touchscreen-m.patch"
HID_PATCH2="${SCRIPT_DIR}/0002-HID-multitouch-Fix-stale-MT-slots-when-contact-count-drops-to-zero.patch"
HID_PATCH3="${SCRIPT_DIR}/0003-HID-multitouch-Suppress-cycling-ghost-contacts-for-Yoga-Book-9.patch"
CDC_PATCH="${SCRIPT_DIR}/0004-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch"
CDC_PATCH3="${SCRIPT_DIR}/0005-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch"
KBDOCK_SRC="${SCRIPT_DIR}/lenovo-yb9-kbdock.c"

echo "==> Rebuilding patches for kernel ${KVER}"

# --------------------------------------------------------------------------
# 1. Build prerequisites
# --------------------------------------------------------------------------
echo "==> Installing build prerequisites..."
sudo dnf install -y rpm-build zstd
if ! rpm -q "kernel-devel-${KVER}" &>/dev/null; then
    echo "==> kernel-devel-${KVER} not installed; attempting dnf install..."
    # Strip arch suffix (.x86_64) for dnf name resolution
    sudo dnf install -y "kernel-devel-${KVER%.*}" || \
        echo "    WARNING: kernel-devel not found in repos — build will use existing /usr/src/kernels/${KVER}"
fi

# --------------------------------------------------------------------------
# 2. Download source RPM (cached by kernel version)
# --------------------------------------------------------------------------
KVER_NVR="kernel-${KVER%.*}"   # e.g. kernel-6.19.12-200.fc43

mkdir -p "${RPM_CACHE}"
SRC_RPM_GLOB="${RPM_CACHE}/${KVER_NVR}.src.rpm"

if ! ls ${SRC_RPM_GLOB} &>/dev/null; then
    echo "==> Downloading kernel source RPM (${KVER_NVR})..."
    pushd "${RPM_CACHE}" >/dev/null
    if ! dnf download --source "${KVER_NVR}" 2>/dev/null; then
        echo "    dnf download unavailable; falling back to koji..."
        if ! command -v koji &>/dev/null; then
            sudo dnf install -y koji
        fi
        koji download-build --arch=src "${KVER_NVR}"
    fi
    popd >/dev/null
else
    echo "==> Source RPM already cached: $(ls ${SRC_RPM_GLOB})"
fi

SRC_RPM="$(ls ${SRC_RPM_GLOB})"

# --------------------------------------------------------------------------
# 3. Extract kernel tarball from RPM (cached per kernel version)
# --------------------------------------------------------------------------
TARBALL_DIR="${RPM_CACHE}"
KVER_BASE="$(echo "${KVER}" | grep -oP '^\d+\.\d+\.\d+')"   # e.g. 7.0.6

if ! ls "${TARBALL_DIR}"/linux-${KVER_BASE}*.tar.xz &>/dev/null; then
    echo "==> Extracting source tarball from RPM..."
    pushd "${TARBALL_DIR}" >/dev/null
    rpm2cpio "${SRC_RPM}" | cpio -idmv '*.tar.xz' 2>/dev/null
    popd >/dev/null
fi

TARBALL="$(ls "${TARBALL_DIR}"/linux-${KVER_BASE}*.tar.xz 2>/dev/null | head -1)"
if [ -z "${TARBALL}" ]; then
    echo "ERROR: no source tarball for ${KVER_BASE} found in ${TARBALL_DIR}" >&2
    exit 1
fi
KVER_SRC="$(basename "${TARBALL}" | grep -oP 'linux-\K[0-9.]+(?=\.tar)')"
echo "==> Source tarball: linux-${KVER_SRC}.tar.xz"

# --------------------------------------------------------------------------
# 4. Set up build directory with fresh driver sources
# --------------------------------------------------------------------------
echo "==> Extracting fresh driver sources into ${BUILD_DIR}..."
mkdir -p "${BUILD_DIR}"

tar xf "${TARBALL}" --strip-components=3 -C "${BUILD_DIR}" \
    "linux-${KVER_SRC}/drivers/hid/hid-multitouch.c" \
    "linux-${KVER_SRC}/drivers/hid/hid-ids.h" \
    "linux-${KVER_SRC}/drivers/hid/hid-haptic.h"

tar xf "${TARBALL}" --strip-components=4 -C "${BUILD_DIR}" \
    "linux-${KVER_SRC}/drivers/usb/class/cdc-acm.c" \
    "linux-${KVER_SRC}/drivers/usb/class/cdc-acm.h"

# yb9-kbdock is a new driver not present in the upstream tree; copy from here.
cp "${KBDOCK_SRC}" "${BUILD_DIR}/yb9-kbdock.c"

# --------------------------------------------------------------------------
# 5. Write Makefile
# --------------------------------------------------------------------------
cat > "${BUILD_DIR}/Makefile" << 'EOF'
obj-m := hid-multitouch.o cdc-acm.o yb9-kbdock.o
EOF

# --------------------------------------------------------------------------
# 6. Apply patches
# --------------------------------------------------------------------------
echo "==> Applying hid-multitouch patch (0001)..."
# git format-patch: a/drivers/hid/hid-multitouch.c → strip 3 components
pushd "${BUILD_DIR}" >/dev/null
patch -p3 < "${HID_PATCH}"
popd >/dev/null

echo "==> Applying hid-multitouch patch (0002)..."
pushd "${BUILD_DIR}" >/dev/null
patch -p3 < "${HID_PATCH2}"
popd >/dev/null

echo "==> Applying hid-multitouch patch (0003)..."
pushd "${BUILD_DIR}" >/dev/null
patch -p3 < "${HID_PATCH3}"
popd >/dev/null

echo "==> Applying cdc-acm patch (0004)..."
# Upstreamed in kernel 7.0+; skip if the source already has ALWAYS_POLL_CTRL.
pushd "${BUILD_DIR}" >/dev/null
if grep -q "ALWAYS_POLL_CTRL" cdc-acm.c; then
    echo "    Already present in upstream source — skipping 0004."
else
    patch cdc-acm.c < "${CDC_PATCH}"
fi
popd >/dev/null

echo "==> Applying cdc-acm patch (0005)..."
# git format-patch: a/drivers/usb/class/cdc-acm.c → strip 4 components
pushd "${BUILD_DIR}" >/dev/null
patch -p4 < "${CDC_PATCH3}"
popd >/dev/null

# --------------------------------------------------------------------------
# 7. Build
# --------------------------------------------------------------------------
echo "==> Building modules against /usr/src/kernels/${KVER}..."
make -C "/usr/src/kernels/${KVER}" M="${BUILD_DIR}" modules

# --------------------------------------------------------------------------
# 8. Install hid-multitouch
# --------------------------------------------------------------------------
echo "==> Installing hid-multitouch.ko.zst..."
pushd "${BUILD_DIR}" >/dev/null

# Install to updates/ so depmod prefers our version over kernel/'s stock copy.
# This survives kernel-core package reinstalls (which only touch kernel/).
sudo install -d "/lib/modules/${KVER}/updates"
zstd -f -19 hid-multitouch.ko -o hid-multitouch.ko.zst
sudo cp hid-multitouch.ko.zst \
    "/lib/modules/${KVER}/updates/hid-multitouch.ko.zst"
popd >/dev/null

# --------------------------------------------------------------------------
# 9. Install cdc-acm
# --------------------------------------------------------------------------
echo "==> Installing cdc-acm.ko.zst..."
pushd "${BUILD_DIR}" >/dev/null

# Install to updates/ for the same reason as hid-multitouch above.
zstd -f -19 cdc-acm.ko -o cdc-acm.ko.zst
sudo cp cdc-acm.ko.zst \
    "/lib/modules/${KVER}/updates/cdc-acm.ko.zst"
popd >/dev/null

# --------------------------------------------------------------------------
# 10. Install yb9-kbdock
# --------------------------------------------------------------------------
echo "==> Installing yb9-kbdock.ko.zst..."
pushd "${BUILD_DIR}" >/dev/null
sudo install -d "/lib/modules/${KVER}/extra"
zstd -f -19 yb9-kbdock.ko -o yb9-kbdock.ko.zst
sudo cp yb9-kbdock.ko.zst "/lib/modules/${KVER}/extra/yb9-kbdock.ko.zst"
popd >/dev/null

# Remove stale extra/ copies — depmod prefers updates/ over extra/ and kernel/.
for mod in hid-multitouch cdc-acm; do
    stale="/lib/modules/${KVER}/extra/${mod}.ko.zst"
    if [ -f "${stale}" ]; then
        echo "==> Removing stale extra/${mod}.ko.zst..."
        sudo rm -f "${stale}"
    fi
done

# --------------------------------------------------------------------------
# 11. Update module dependencies
# --------------------------------------------------------------------------
echo "==> Running depmod -a..."
sudo depmod -a

# --------------------------------------------------------------------------
# 12. Reload modules and re-enumerate INGENIC USB device
# --------------------------------------------------------------------------
echo "==> Reloading modules..."

sudo modprobe -r hid_multitouch 2>/dev/null || true
sudo modprobe hid_multitouch \
    && echo "    hid_multitouch loaded" \
    || echo "    WARNING: hid_multitouch load failed — reboot required"

sudo modprobe -r cdc_acm 2>/dev/null || true
sudo modprobe cdc_acm \
    && echo "    cdc_acm loaded" \
    || echo "    WARNING: cdc_acm load failed — reboot required"

sudo modprobe -r yb9_kbdock lenovo_yb9_kbdock 2>/dev/null || true
sudo modprobe yb9_kbdock \
    && echo "    yb9_kbdock loaded" \
    || echo "    WARNING: yb9_kbdock load failed — reboot required"

# Force a full USB re-enumeration of the INGENIC device.  A simple
# modprobe cycle is not enough: the firmware sends a persistent ghost
# contact at probe time that is only cleared by the Input Mode
# SET_REPORT issued during hid-multitouch probe().  That SET_REPORT
# only reaches the firmware if it arrives as part of a fresh USB
# enumeration sequence (deauthorize → reauthorize triggers a USB reset
# and a new enumeration, after which probe() runs from scratch).
echo "==> Re-enumerating INGENIC USB device to flush firmware ghost contact..."
INGENIC_USB=""
for idv in /sys/bus/usb/devices/*/idVendor; do
    d="$(dirname "$idv")"
    if [ "$(cat "$d/idVendor" 2>/dev/null)" = "17ef" ] && \
       [ "$(cat "$d/idProduct" 2>/dev/null)" = "6161" ]; then
        INGENIC_USB="$d"
        break
    fi
done
if [ -n "$INGENIC_USB" ]; then
    echo "    Device: ${INGENIC_USB##*/}"
    echo 0 | sudo tee "$INGENIC_USB/authorized" >/dev/null
    sleep 1
    echo 1 | sudo tee "$INGENIC_USB/authorized" >/dev/null
    sleep 2
    echo "    Re-enumeration complete."
else
    echo "    WARNING: INGENIC 17EF:6161 USB device not found — reboot to clear ghost contact"
fi

# --------------------------------------------------------------------------
# 13. Restart touchpad daemon
# --------------------------------------------------------------------------
DAEMON_BIN="/usr/lib64/libexec/plasma-touchpad-daemon"
DAEMON_LOG="/tmp/plasma-touchpad.log"

if [ -x "${DAEMON_BIN}" ]; then
    echo "==> Restarting plasma-touchpad-daemon..."
    pkill -f plasma-touchpad-daemon 2>/dev/null || true
    sleep 0.3
    nohup "${DAEMON_BIN}" >>"${DAEMON_LOG}" 2>&1 &
    DAEMON_PID=$!
    sleep 0.5
    if kill -0 "${DAEMON_PID}" 2>/dev/null; then
        echo "    plasma-touchpad-daemon started (PID ${DAEMON_PID})"
    else
        echo "    WARNING: plasma-touchpad-daemon exited immediately — check ${DAEMON_LOG}"
    fi
else
    echo "    Skipping daemon restart: ${DAEMON_BIN} not found"
fi

# --------------------------------------------------------------------------
# 14. Unbind/rebind hid-multitouch for INGENIC device to clear ghost state
# --------------------------------------------------------------------------
echo "==> Clearing ghost state: unbinding hid-multitouch from INGENIC device..."
# Find the hid-multitouch-bound device entry for 17EF:6161
HID_MT_DEV=$(ls /sys/bus/hid/drivers/hid-multitouch/ 2>/dev/null \
    | grep -i "17EF:6161" | head -1)

if [ -n "$HID_MT_DEV" ]; then
    echo "    Device: ${HID_MT_DEV}"
    echo "${HID_MT_DEV}" | sudo tee /sys/bus/hid/drivers/hid-multitouch/unbind >/dev/null
    sleep 1
    echo "${HID_MT_DEV}" | sudo tee /sys/bus/hid/drivers/hid-multitouch/bind >/dev/null
    sleep 1
    echo "    Ghost state cleared."
else
    echo "    WARNING: INGENIC hid-multitouch device not found; ghost state not cleared"
fi

# --------------------------------------------------------------------------
echo ""
echo "==> Done. Patches installed and loaded for ${KVER}."
