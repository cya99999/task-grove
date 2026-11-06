"""Expose only a compatible, app-local Fcitx plugin to the bundled Qt runtime."""
import os
from pathlib import Path
import sys
from PySide6.QtCore import QCoreApplication, QPluginLoader, qVersion


def configure_input_method():
    """Call before QApplication; do not expose all of the system's Qt plugins."""
    if sys.platform != 'linux':
        return None
    requested = os.environ.get('QT_IM_MODULE', '')
    if requested and requested != 'fcitx':
        return None
    if not requested and '@im=fcitx' not in os.environ.get('XMODIFIERS', ''):
        return None
    root = Path(__file__).resolve().parent.parent / '.qt-plugins' / qVersion()
    plugins = root / 'platforminputcontexts'
    # Load bundled QtDBus first, so dlopen never resolves to the system Qt ABI.
    from PySide6 import QtGui, QtDBus  # noqa: F401
    for candidate in sorted(plugins.glob('libfcitx*platforminputcontext*.so')):
        loader = QPluginLoader(str(candidate))
        if loader.load():
            QCoreApplication.addLibraryPath(str(root))
            os.environ.setdefault('QT_IM_MODULE', 'fcitx')
            return candidate
        print(f'枝序输入法插件无法加载：{loader.errorString()}', file=sys.stderr)
    return None
