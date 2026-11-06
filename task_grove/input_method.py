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


_last_mode = None


def capture_input_mode(fallback=True):
    """Remember Fcitx's current mode BEFORE a new window creates its input context."""
    import subprocess
    global _last_mode
    if (sys.platform != 'linux' or os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
            or os.environ.get('QT_IM_MODULE') != 'fcitx'):
        return None
    try:
        value = subprocess.run(['fcitx-remote'], capture_output=True, text=True, timeout=.4).stdout.strip()
        if value in ('1', '2'):
            _last_mode = int(value)
            return _last_mode
        return _last_mode if fallback else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def restore_input_mode(mode, window):
    """Fcitx 4 defaults new top-level contexts to English; inherit the prior mode."""
    from PySide6.QtCore import QTimer
    if mode not in (1, 2):
        return

    def restore(attempt=0):
        import subprocess
        global _last_mode
        if not window.isVisible():
            return
        current = capture_input_mode(fallback=False) if window.isActiveWindow() else None
        if current is None:
            # Fcitx reports 0 while CreateIC/FocusIn is still pending. An early
            # activation command would target no input context and be lost.
            if attempt < 40:
                QTimer.singleShot(25, window, lambda: restore(attempt + 1))
            return
        if current == mode:
            return
        try:
            subprocess.run(['fcitx-remote', '-o' if mode == 2 else '-c'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=.4)
            _last_mode = mode
        except (OSError, subprocess.TimeoutExpired):
            pass
    QTimer.singleShot(0, window, restore)
