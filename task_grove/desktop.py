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
            'Comment=思维导图式任务拆解与管理器\n'
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


def launch_preferred_checkout():
    """Use the user's selected desktop checkout unless isolated local data was requested."""
    if any(arg == '--local' or arg == '--data-dir' or arg.startswith('--data-dir=') for arg in sys.argv[1:]):
        return
    preference = CONFIG / 'task-grove/desktop-checkout'
    if not preference.exists():
        return
    target = Path(preference.read_text().strip()).expanduser().resolve()
    if target == ROOT.resolve():
        return
    python = target / '.venv/bin/python'
    if not python.is_file() or not (target / 'task_grove/app.py').is_file():
        raise RuntimeError('配置的桌面版本不存在，请检查 ~/.config/task-grove/desktop-checkout')
    os.chdir(target)
    os.execv(str(python), [str(python), '-m', 'task_grove.app', *sys.argv[1:]])
