"""Freedesktop launcher/autostart integration (user account only)."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
AUTOSTART = CONFIG / 'autostart/task-grove.desktop'


def desktop_entry(background=False):
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    return ('[Desktop Entry]\nType=Application\nName=枝序 Task Grove\n'
            'Comment=把下一步放回树上，让空档时间有处可去\n'
            f'Exec={quote(sys.executable)} -m task_grove.app' + (' --background' if background else '') + '\n'
            f'Path={ROOT}\nIcon={ROOT / "assets/icon.svg"}\n'
            'Terminal=false\nCategories=Office;ProjectManagement;\n'
            'StartupNotify=false\nX-GNOME-Autostart-enabled=true\n')


def set_autostart(enabled):
    if enabled:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(desktop_entry(True))
    else:
        AUTOSTART.unlink(missing_ok=True)


def install(autostart=True):
    launcher = DATA / 'applications/task-grove.desktop'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(desktop_entry())
    launcher.chmod(0o755)
    set_autostart(autostart)
    return launcher
