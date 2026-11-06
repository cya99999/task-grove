"""Headless integration checks; run with QT_QPA_PLATFORM=offscreen."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData
from PySide6.QtGui import QDropEvent, QDragEnterEvent, QDragMoveEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from task_grove.app import Window, STYLE, MIME, TaskDialog
from task_grove.model import Forest

APP = QApplication.instance() or QApplication([])
APP.setOrganizationName('TaskGroveTests')
APP.setApplicationName('test')
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

    def test_click_completes_and_undo_restores(self):
        self.window.locate('read')
        card = self.window.view.cards['read']
        pos = self.window.view.mapFromScene(card.pos() + QPointF(70, 30))
        QTest.mouseClick(self.window.view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        APP.processEvents()
        self.assertNotIn('read', self.forest.nodes)
        self.assertIn('note', self.forest.nodes['learn']['children'])
        self.window.perform(self.forest.undo)
        APP.processEvents()
        self.assertIn('read', self.window.view.cards)

    def test_filter_only_ready_and_known_short_tasks(self):
        self.window.time_filter.setCurrentIndex(1)
        APP.processEvents()
        self.assertEqual(self.window.ready_list.count(), 3)
        self.assertIn('3 项', self.window.ready_label.text())

    def test_drop_changes_parent_and_updates_canvas(self):
        view = self.window.view
        mime = QMimeData()
        mime.setData(MIME, b'readlog')
        card = view.cards['life']
        pos = view.mapFromScene(card.pos() + QPointF(80, 40))
        enter = QDragEnterEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
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
        item = sidebar.item(3)  # life category after all/dev/learn
        pos = sidebar.visualItemRect(item).center()
        drop = QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        sidebar.dropEvent(drop)
        APP.processEvents()
        self.assertEqual(self.forest.category('note'), 'life')

    def test_search_reveals_collapsed_ancestor(self):
        self.forest.edit('learn', collapsed=True)
        self.window.refresh()
        self.assertNotIn('note', self.window.view.cards)
        self.window.search.setText('写下一个理解')
        APP.processEvents()
        self.assertIn('note', self.window.view.cards)

    def test_dialog_preserves_wait_deadline_when_editing_title(self):
        node = self.forest.nodes['run']
        dialog = TaskDialog(self.window, '编辑', node)
        dialog.name.setText('改名')
        self.assertEqual(dialog.values()['wait_until'], node['wait_until'])
        dialog.wait.setValue(0)
        self.assertEqual(dialog.values()['wait_until'], 0)

    def test_timer_marks_due_once_without_completing(self):
        self.forest.edit('run', wait_until=1)
        self.window.tick()
        self.assertIn(('run', 1), self.window.notified)
        self.assertIn('run', self.forest.nodes)
        self.window.tick()
        self.assertEqual(len(self.window.notified), 1)

    def test_render_and_screenshot(self):
        self.assertEqual(len(self.window.view.cards), len(self.forest.nodes))
        target = os.environ.get('TASK_GROVE_SCREENSHOT')
        if target:
            self.assertTrue(self.window.grab().save(target))


if __name__ == '__main__':
    unittest.main()
