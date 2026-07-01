#!/bin/bash
# RPMCleanup.sh
# Run after building python3-dlib and configuring howdy.
# Removes all build dependencies that are no longer needed.

set -e

echo "==> Removing build dependencies..."
sudo dnf remove -y \
    rpm-build \
    rpmdevtools \
    boost-devel \
    cmake \
    cmake-rpm-macros \
    pybind11-devel \
    gcc-c++ \
    gcc-gfortran \
    fftw-devel \
    flexiblas-devel \
    ffmpeg-free-devel \
    libpng-devel \
    libX11-devel \
    libjxl-devel \
    python3-devel \
    pyproject-rpm-macros \
    libv4l-devel \
    sqlite-devel \
    make

echo "==> Removing orphaned dependencies..."
sudo dnf autoremove -y

echo "==> Cleaning up RPM build tree..."
rm -rf ~/rpmbuild/BUILD
rm -rf ~/rpmbuild/BUILDROOT
rm -rf ~/rpmbuild/SRPMS
rm -f ~/rpmbuild/SOURCES/v19.24.6.tar.gz

echo "==> Clearing pip cache..."
pip3 cache purge 2>/dev/null || true

echo ""
echo "Done. The following files are kept intentionally:"
echo "  ~/rpmbuild/SPECS/dlib.spec       — rebuild dlib if needed"
echo "  ~/rpmbuild/RPMS/x86_64/dlib-*.rpm"
echo "  ~/rpmbuild/RPMS/x86_64/python3-dlib-*.rpm"
echo ""
echo "To reinstall python3-dlib without rebuilding:"
echo "  sudo dnf install ~/rpmbuild/RPMS/x86_64/python3-dlib-*.rpm"
