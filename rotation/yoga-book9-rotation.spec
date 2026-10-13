Name:           yoga-book9-rotation
Version:        1.0
Release:        1%{?dist}
Summary:        Dual-screen auto-rotation daemon for Lenovo Yoga Book 9 14IAH10
License:        GPL-2.0-or-later
URL:            https://github.com/carvsdriver/yoga-book9-rotation
Source0:        %{url}/archive/refs/tags/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  systemd-rpm-macros

Requires:       iio-sensor-proxy
Requires:       python3
Requires:       python3-dbus
Requires:       python3-gobject
Requires:       kscreen

%description
Provides dual-screen synchronized auto-rotation and tent mode detection
for the Lenovo Yoga Book 9 14IAH10 (model 83KJ) running KDE on Wayland.

Subscribes to iio-sensor-proxy for AccelerometerOrientation and reads
both on-board accelerometers directly from sysfs (no patched binary
required) to detect tent mode.  Applies the correct complementary
rotation to eDP-1 (top screen, physically inverted) and eDP-2 (bottom
screen) via kscreen-doctor.

A systemd user preset auto-enables the service so it starts on login.
To enable manually:
  systemctl --user enable --now yoga9-rotate.service

If upgrading from the screen-rotate system service, first run:
  sudo systemctl disable --now screen-rotate.service

%prep
%autosetup -n %{name}-%{version}

%build
# nothing to build

%install
install -Dm755 yoga9-rotate.py \
    %{buildroot}%{_libexecdir}/yoga9-rotate
install -Dm644 yoga9-rotate.service \
    %{buildroot}%{_userunitdir}/yoga9-rotate.service
install -Dm644 yoga9-rotate.preset \
    %{buildroot}%{_prefix}/lib/systemd/user-preset/50-yoga9-rotate.preset
install -Dm644 61-sensor-yogabook9.rules \
    %{buildroot}%{_udevrulesdir}/61-sensor-yogabook9.rules

%post
%systemd_user_post yoga9-rotate.service
# Reload udev rules and re-trigger IIO devices so the mount matrix takes
# effect immediately without a reboot.
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=iio || :
systemctl restart iio-sensor-proxy.service || :

%preun
%systemd_user_preun yoga9-rotate.service

%postun
%systemd_user_postun_with_restart yoga9-rotate.service

%files
%license LICENSE
%{_libexecdir}/yoga9-rotate
%{_userunitdir}/yoga9-rotate.service
%{_prefix}/lib/systemd/user-preset/50-yoga9-rotate.preset
%{_udevrulesdir}/61-sensor-yogabook9.rules

%changelog
* Thu Jun 25 2026 Dave Carey <carvsdriver@gmail.com> - 1.0-1
- Initial package
- Event-driven rotation via iio-sensor-proxy D-Bus (AccelerometerOrientation)
- Tent mode detection by direct sysfs comparison of both accel Y-axes
- Systemd user service with preset; no patched iio-sensor-proxy binary needed
