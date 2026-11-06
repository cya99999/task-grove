#!/usr/bin/env python3
"""Build Fcitx 4's Qt6 input plugin against the SAME Qt as this app.

Needs a matching official QtBase SDK, CMake, a compiler, ECM, and XKB/OpenGL
headers. Optional --dev-prefix points at unpacked development packages.
No system installation or sudo; output stays in .qt-plugins/<Qt version>.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from PySide6.QtCore import QLibraryInfo, QPluginLoader, qVersion
from PySide6 import QtGui, QtDBus  # Preload bundled Qt libraries before dlopen.

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'c328b03f32a4276d9aeb3213d1f3f959ef6848f2'


def run(*command, **kwargs):
    subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qt-prefix', required=True, type=Path)
    parser.add_argument('--dev-prefix', type=Path, help='Directory containing include/ and share/ECM/')
    parser.add_argument('--source', type=Path, help='Optional existing fcitx/fcitx-qt5 source checkout')
    args = parser.parse_args()
    qt = args.qt_prefix.resolve()
    config = qt / 'include/QtCore/qtcoreversion.h'
    if not config.exists() or f'"{qVersion()}"' not in config.read_text():
        parser.error(f'QtBase SDK must match PySide6 Qt {qVersion()} exactly')
    deps = args.dev_prefix.resolve() if args.dev_prefix else Path('/usr')
    system_lib = Path('/usr/lib') / sysconfig.get_config_var('MULTIARCH')
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = QLibraryInfo.path(QLibraryInfo.LibraryPath.LibrariesPath) + ':' + env.get('LD_LIBRARY_PATH', '')
    with tempfile.TemporaryDirectory(prefix='task-grove-fcitx-') as temp:
        source, build = Path(temp) / 'source', Path(temp) / 'build'
        if args.source:
            shutil.copytree(args.source, source, ignore=shutil.ignore_patterns('.git'))
        else:
            run('git', 'init', source)
            run('git', '-C', source, 'fetch', '--depth=1', 'https://github.com/fcitx/fcitx-qt5.git', REVISION)
            run('git', '-C', source, 'checkout', '--detach', 'FETCH_HEAD')
        cmake = source / 'qt6/platforminputcontext/CMakeLists.txt'
        if 'Qt6::GuiPrivate' not in cmake.read_text():
            cmake.write_text(cmake.read_text().replace('Qt6::Gui\n', 'Qt6::Gui\n                          Qt6::GuiPrivate\n'))
        run('cmake', '-S', source, '-B', build, '-G', 'Ninja',
            '-DENABLE_QT5=OFF', '-DENABLE_QT6=ON', '-DENABLE_LIBRARY=OFF',
            '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_SKIP_RPATH=ON', '-DQT_FIND_PRIVATE_MODULES=ON',
            f'-DCMAKE_PREFIX_PATH={qt};{deps}',
            f'-DXKBCommon_XKBCommon_LIBRARY={system_lib / "libxkbcommon.so.0"}',
            f'-DXKBCommon_XKBCommon_INCLUDE_DIR={deps / "include"}',
            f'-DXKB_LIBRARY={system_lib / "libxkbcommon.so.0"}',
            f'-DXKB_INCLUDE_DIR={deps / "include"}',
            f'-DOPENGL_opengl_LIBRARY={system_lib / "libOpenGL.so.0"}',
            f'-DOPENGL_glx_LIBRARY={system_lib / "libGLX.so.0"}',
            f'-DOPENGL_INCLUDE_DIR={deps / "include"}', env=env)
        run('cmake', '--build', build, '-j', '4', env=env)
        binary = build / 'qt6/platforminputcontext/libfcitxplatforminputcontextplugin-qt6.so'
        loader = QPluginLoader(str(binary))
        if not loader.load():
            raise RuntimeError(loader.errorString())
        destination = ROOT / '.qt-plugins' / qVersion() / 'platforminputcontexts'
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, destination)
        for name in ('COPYING', 'COPYING.BSD'):
            shutil.copy2(source / name, destination.parent / name)
        print('Installed compatible input plugin:', destination / binary.name)
        print('Restart Task Grove to activate it.')


if __name__ == '__main__':
    main()
