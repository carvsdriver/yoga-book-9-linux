%global version 19.24.6

Name:           dlib
Version:        %{version}
Release:        1%{?dist}
Summary:        A modern C++ toolkit containing machine learning algorithms
License:        BSL-1.0
URL:            http://dlib.net
Source0:        https://github.com/davisking/dlib/archive/refs/tags/v%{version}.tar.gz

BuildRequires:  boost-devel
BuildRequires:  cmake
BuildRequires:  cmake(pybind11)
BuildRequires:  gcc-c++
BuildRequires:  gcc-gfortran
BuildRequires:  pkgconfig(fftw3)
BuildRequires:  pkgconfig(flexiblas)
BuildRequires:  pkgconfig(libavcodec)
BuildRequires:  pkgconfig(libavdevice)
BuildRequires:  pkgconfig(libavfilter)
BuildRequires:  pkgconfig(libavformat)
BuildRequires:  pkgconfig(libavutil)
BuildRequires:  pkgconfig(libpng)
BuildRequires:  pkgconfig(libjpeg)
BuildRequires:  pkgconfig(sqlite3)
BuildRequires:  pkgconfig(x11)
BuildRequires:  libjxl-devel
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros

%description
Dlib is a general purpose cross-platform C++ library with machine learning,
image processing, and numerical optimization components.

%package devel
Summary:        Development files for dlib
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description devel
Development headers and libraries for dlib.

%package -n python3-%{name}
Summary:        Python 3 interface to dlib

%description -n python3-%{name}
Python 3 bindings for the dlib machine learning library.

%prep
%autosetup -n %{name}-%{version}
rm -r dlib/external/pybind11
sed -i 's@add_subdirectory(../../dlib/external/pybind11 pybind11_build)@find_package(pybind11 CONFIG)@' tools/python/CMakeLists.txt

%generate_buildrequires
%pyproject_buildrequires

%build
%cmake \
    -DCMAKE_BUILD_TYPE:STRING=RelWithDebInfo \
    -DDLIB_USE_CUDA:BOOL=OFF \
    -DDLIB_JXL_SUPPORT:BOOL=ON
%cmake_build
%pyproject_wheel

%install
%cmake_install
%pyproject_install
%pyproject_save_files -l %{name}

%files
%license LICENSE.txt
%{_libdir}/libdlib.so.19*

%files devel
%{_libdir}/libdlib.so
%{_includedir}/dlib/
%{_libdir}/cmake/dlib/
%{_libdir}/pkgconfig/*.pc

%files -n python3-%{name} -f %{pyproject_files}
%{python3_sitearch}/_dlib_pybind11*.so
%doc README.md

%changelog
* Tue Mar 24 2026 Local Build <local@build> - 19.24.6-1
- Local build for Fedora 43 Python 3.14
