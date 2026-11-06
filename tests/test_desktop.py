"""Selecting a checkout must preserve isolated local startup."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from task_grove import desktop


class PreferredCheckoutTests(unittest.TestCase):
    def test_selected_checkout_is_launched_with_original_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'config';target=Path(folder)/'selected'
            (config/'task-grove').mkdir(parents=True)
            (target/'.venv/bin').mkdir(parents=True);(target/'task_grove').mkdir()
            (target/'.venv/bin/python').touch();(target/'task_grove/app.py').touch()
            (config/'task-grove/desktop-checkout').write_text(str(target))
            with patch.object(desktop,'CONFIG',config),patch.object(desktop.sys,'argv',['app','--background']),patch.object(desktop.os,'chdir') as chdir,patch.object(desktop.os,'execv') as execute:
                desktop.launch_preferred_checkout()
                chdir.assert_called_once_with(target)
                execute.assert_called_once_with(str(target/'.venv/bin/python'),[str(target/'.venv/bin/python'),'-m','task_grove.app','--background'])

    def test_local_and_isolated_launch_never_redirect(self):
        for arg in ('--local','--data-dir','--data-dir=/tmp/test'):
            with patch.object(desktop.sys,'argv',['app',arg]),patch.object(desktop.os,'execv') as execute:
                desktop.launch_preferred_checkout();execute.assert_not_called()

    def test_same_checkout_never_recurses(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder);(config/'task-grove').mkdir()
            (config/'task-grove/desktop-checkout').write_text(str(desktop.ROOT))
            with patch.object(desktop,'CONFIG',config),patch.object(desktop.sys,'argv',['app']),patch.object(desktop.os,'execv') as execute:
                desktop.launch_preferred_checkout();execute.assert_not_called()
