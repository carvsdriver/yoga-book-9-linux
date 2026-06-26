#!/usr/bin/env bash
# Build a source RPM (SRPM) from the local working tree.
# Usage: ./make-srpm.sh [version]
# The SRPM lands in ~/rpmbuild/SRPMS/ and can be uploaded to COPR.

set -euo pipefail

VERSION=${1:-1.0}
PKGNAME="yoga-book9-rotation"
TARNAME="${PKGNAME}-${VERSION}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

SRCDIR="${TMPDIR}/${TARNAME}"
mkdir "$SRCDIR"

cp yoga9-rotate.py          "$SRCDIR/"
cp yoga9-rotate.service     "$SRCDIR/"
cp yoga9-rotate.preset      "$SRCDIR/"
cp 61-sensor-yogabook9.rules "$SRCDIR/"

tar -czf "${TMPDIR}/${TARNAME}.tar.gz" -C "$TMPDIR" "$TARNAME"

mkdir -p ~/rpmbuild/SOURCES ~/rpmbuild/SPECS
cp "${TMPDIR}/${TARNAME}.tar.gz" ~/rpmbuild/SOURCES/
cp yoga-book9-rotation.spec ~/rpmbuild/SPECS/

rpmbuild -bs ~/rpmbuild/SPECS/yoga-book9-rotation.spec \
    --define "version ${VERSION}"

echo
echo "SRPM built:"
ls ~/rpmbuild/SRPMS/${PKGNAME}-*.src.rpm
echo
echo "To upload to COPR:"
echo "  copr-cli build <your-project> ~/rpmbuild/SRPMS/${PKGNAME}-*.src.rpm"
