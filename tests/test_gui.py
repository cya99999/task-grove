"""Qt integration tests, using an isolated offscreen desktop and data directory."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPointF, QMimeData, QDateTime
from PySide6.QtGui import QDropEvent, QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from task_grove.app import Window, STYLE, MIME, TaskDialog
from task_grove.model import Forest

APP = QApplication.instance() or QApplication([])
APP.setOrganizationName('TaskGroveTests')
APP.setApplicationName('test-v2')
APP.setStyleSheet(STYLE)


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.forest = Forest(Path(self.tmp.name) / 'tasks.json')
        self.forest.seed_example()
        self.window = Window(self.forest, tray_enabled=False)
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.timer.stop()
        self.window.quitting = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.tmp.cleanup()

    def click_card(self, key, x, y):
        self.window.locate(key)
        card = self.window.view.cards[key]
        pos = self.window.view.mapFromScene(card.pos() + QPointF(x, y))
        QTest.mouseClick(self.window.view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        APP.processEvents()

    def test_text_selects_and_checkbox_completes_with_undo(self):
        self.click_card('read', 70, 30)
        self.assertIn('read', self.forest.nodes)
        self.assertEqual(self.window.selected_node, 'read')
        self.click_card('read', 22, 30)
        self.assertNotIn('read', self.forest.nodes)
        self.assertIn('note', self.forest.nodes['learn']['children'])
        self.window.perform(self.forest.undo)
        APP.processEvents()
        self.assertIn('read', self.window.view.cards)

    def test_right_click_opens_edit_directly(self):
        self.window.locate('read')
        card = self.window.view.cards['read']
        pos = self.window.view.mapFromScene(card.pos() + QPointF(80, 35))
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos)
        with patch.object(self.window, 'edit_task') as edit:
            QApplication.sendEvent(self.window.view.viewport(), event)
            edit.assert_called_once_with('read')

    def test_all_trees_start_collapsed_but_category_shows_steps(self):
        self.assertEqual(set(self.window.view.cards), set(self.forest.data['roots']))
        self.window.toggle_branch('learn')
        APP.processEvents()
        self.assertIn('read', self.window.view.cards)
        self.window.locate('note')
        self.assertIn('note', self.window.view.cards)
        self.window.categories.setCurrentRow(0)
        APP.processEvents()
        self.assertEqual(set(self.window.view.cards), set(self.forest.data['roots']))

    def test_scheduled_list_includes_deep_nodes_across_categories(self):
        self.forest.edit('note', due_at=time.time() + 500)
        self.window.locate('water')
        self.window.refresh_scheduled()
        self.assertIn('2 项', self.window.ready_label.text())
        self.assertEqual(self.window.ready_list.count(), 2)

    def test_drop_changes_parent_and_saves(self):
        view = self.window.view
        mime = QMimeData()
        mime.setData(MIME, b'readlog')
        card = view.cards['life']
        pos = view.mapFromScene(card.pos() + QPointF(80, 40))
        drop = QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        APP.processEvents()
        self.assertEqual(self.forest.parent('readlog'), 'life')
        self.assertEqual(Forest(self.forest.path).data, self.forest.data)

    def test_sidebar_drop_moves_whole_subtree(self):
        sidebar = self.window.categories
        mime = QMimeData()
        mime.setData(MIME, b'read')
        item = next(sidebar.item(i) for i in range(sidebar.count()) if sidebar.item(i).data(Qt.ItemDataRole.UserRole) == 'life')
        pos = sidebar.visualItemRect(item).center()
        drop = QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        sidebar.dropEvent(drop)
        APP.processEvents()
        self.assertEqual(self.forest.category('note'), 'life')

    def test_search_reveals_collapsed_ancestor(self):
        self.forest.edit('learn', collapsed=True)
        self.window.refresh()
        self.window.search.setText('写下一个理解')
        APP.processEvents()
        self.assertIn('note', self.window.view.cards)

    def test_dialog_schedule_can_be_set_and_cleared_without_rounding_unchanged_time(self):
        original = time.time() + 3600.123
        node = dict(title='测试', start_at=original, due_at=0)
        dialog = TaskDialog(self.window, '编辑', node)
        self.assertEqual(dialog.values()['start_at'], original)
        enabled, editor = dialog.time_inputs['due_at']
        enabled.setChecked(True)
        editor.setDateTime(QDateTime.fromSecsSinceEpoch(int(original + 60)))
        self.assertEqual(dialog.values()['due_at'], int(original + 60))
        dialog.time_inputs['start_at'][0].setChecked(False)
        self.assertEqual(dialog.values()['start_at'], 0)

    def test_new_category_and_reveal_preserve_maximized_window(self):
        self.window.showMaximized()
        APP.processEvents()
        with patch.object(TaskDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            self.window.new_category()
        self.window.reveal()
        APP.processEvents()
        self.assertTrue(self.window.isMaximized())

    def test_tick_delivers_reminders_once_without_removing_tasks(self):
        self.forest.edit('run', start_at=time.time() + 500)
        with patch.object(self.window, 'notify') as notify:
            self.window.tick()
            count = notify.call_count
            self.assertGreater(count, 0)
            self.window.tick()
            self.assertEqual(notify.call_count, count)
        self.assertIn('run', self.forest.nodes)

    def test_inbox_edit_dialog_cannot_rename_or_delete_root(self):
        dialog = TaskDialog(self.window, '编辑', self.forest.nodes[self.forest.inbox], category=True, inbox=True)
        self.assertTrue(dialog.name.isReadOnly())


if __name__ == '__main__':
    unittest.main()
