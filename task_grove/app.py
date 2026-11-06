"""Native Qt desktop UI. Run with python -m task_grove.app."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import (Qt, QPointF, QRectF, QTimer, QMimeData, QSettings,
                            QLockFile, QStandardPaths)
from PySide6.QtGui import (QAction, QColor, QPainter, QPen, QBrush, QFont,
                           QPainterPath, QIcon, QPixmap, QDrag, QKeySequence, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QListWidget,
    QListWidgetItem, QGraphicsView, QGraphicsScene, QGraphicsObject, QMenu,
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QMessageBox,
    QFileDialog, QSystemTrayIcon, QFrame, QAbstractItemView, QSizePolicy)

from .model import Forest, InvalidTree
from . import desktop

MIME = 'application/x-task-grove-node'
GREEN = '#28664f'
INK = '#253e33'
MUTED = '#7c8c82'
CARD_W, CARD_H = 210, 82
COL, ROW = 278, 112

STYLE = '''
QMainWindow, QDialog { background: #f7f9f5; color: #253e33; }
QWidget { font-size: 13px; color: #253e33; }
QLabel#brand { font-size: 24px; font-weight: 700; color: #28664f; }
QLabel#eyebrow { color: #7c8c82; font-size: 11px; }
QLabel#heading { font-size: 20px; font-weight: 600; }
QLabel#muted { color: #7c8c82; font-size: 12px; }
QPushButton { background: #fff; border: 1px solid #dce5db; border-radius: 8px; padding: 7px 12px; }
QPushButton:hover { background: #eaf1e7; border-color: #b5c9b6; }
QPushButton:pressed { background: #dce9d9; }
QPushButton#primary { background: #28664f; color: white; border-color: #28664f; }
QPushButton#primary:hover { background: #34795e; }
QPushButton#quiet { background: transparent; border: none; color: #64786a; }
QPushButton:disabled { color: #b1bcb2; background: #f1f3ef; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #dce5db; border-radius: 7px; padding: 7px; }
QLineEdit:focus { border: 1px solid #79a68d; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 10px 8px; border-radius: 8px; margin: 2px 0px; }
QListWidget::item:selected { background: #e4eddf; color: #28664f; }
QListWidget::item:hover { background: #edf2e9; }
QListWidget#ready::item { background: white; padding: 0px; margin: 3px 0px; }
QFrame#sidebar { background: #eef2e9; border-right: 1px solid #e0e6db; }
QMenu { background: #fff; border: 1px solid #dce5db; padding: 5px; }
QMenu::item { padding: 8px 22px; border-radius: 4px; }
QMenu::item:selected { background: #e4eddf; }
QScrollBar:vertical { width: 9px; background: transparent; }
QScrollBar::handle:vertical { background: #c7d4c5; border-radius: 4px; min-height: 25px; }
QScrollBar:horizontal { height: 9px; background: transparent; }
QScrollBar::handle:horizontal { background: #c7d4c5; border-radius: 4px; min-width: 25px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QToolTip { background: #253e33; color: white; border: none; padding: 6px; }
'''


def icon():
    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(GREEN))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, 128, 128, 30, 30)
    p.setPen(QPen(QColor('#e7f4dd'), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(64, 99, 64, 29)
    p.drawLine(64, 75, 36, 49)
    p.drawLine(64, 61, 91, 35)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#c9e4ae'))
    for x, y in ((36, 49), (91, 35), (64, 29)):
        p.drawEllipse(QPointF(x, y), 12, 12)
    p.end()
    return QIcon(pix)


def button(text, callback, primary=False):
    item = QPushButton(text)
    if primary:
        item.setObjectName('primary')
    item.clicked.connect(callback)
    return item


class TaskDialog(QDialog):
    def __init__(self, parent, title, node=None, category=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(390)
        self.category = category
        form = QFormLayout(self)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(14)
        self.name = QLineEdit((node or {}).get('title', ''))
        self.name.setMaxLength(200)
        self.name.setPlaceholderText('写下一个具体、能开始的动作')
        form.addRow('名称', self.name)
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 1440)
        self.minutes.setSpecialValueText('未估时')
        self.minutes.setSuffix(' 分钟')
        self.minutes.setValue((node or {}).get('minutes', 0))
        self.wait = QSpinBox()
        self.wait.setRange(0, 10080)
        self.wait.setSpecialValueText('现在可做')
        self.wait.setSuffix(' 分钟后提醒')
        self.original_wait = (node or {}).get('wait_until', 0)
        self.wait.setValue(max(0, int((self.original_wait - time.time() + 59) // 60)))
        self.wait_changed = False
        self.wait.valueChanged.connect(lambda: setattr(self, 'wait_changed', True))
        if not category:
            form.addRow('预计用时', self.minutes)
            form.addRow('等待时间', self.wait)
            hint = QLabel('等待适合编译、训练或下载；到时提醒你手动完成。\n树枝表示先后关系，同层分支可以并行。')
            hint.setObjectName('muted')
            form.addRow(hint)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText('保存')
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        self.name.textChanged.connect(lambda text: actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip())))
        actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.name.text().strip()))
        form.addRow(actions)
        self.name.setFocus()

    def values(self):
        waiting = self.original_wait
        if self.wait_changed:
            waiting = time.time() + self.wait.value() * 60 if self.wait.value() else 0
        return dict(title=self.name.text().strip(), minutes=self.minutes.value(), wait_until=waiting)


class Card(QGraphicsObject):
    def __init__(self, window, key, ready=False):
        super().__init__()
        self.window, self.key, self.ready = window, key, ready
        self.node = window.forest.nodes[key]
        self.root = self.node['kind'] == 'category'
        self.hover = False
        self.pressed = None
        self.moved = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(self.node['title'] + '\n' + ('点击 ＋ 添加步骤；右键管理分类' if self.root else
            '点击任务完成 · 拖拽移动整条分支 · 右键插入、编辑或等待'))

    def boundingRect(self):
        return QRectF(-3, -3, CARD_W + 6, CARD_H + 6)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        query = self.window.search.text().strip().casefold()
        matched = query and query in self.node['title'].casefold()
        fill = GREEN if self.root else ('#f0f6e9' if self.hover else '#ffffff')
        border = '#d7e3d3' if not self.ready else '#8cb59a'
        if matched:
            border = '#e2a43d'
        p.setPen(QPen(QColor(border), 2 if self.hover or matched else 1))
        p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(0, 0, CARD_W, CARD_H), 13, 13)
        color = '#ffffff' if self.root else INK
        p.setPen(QColor(color))
        font = QFont(self.window.font())
        font.setPixelSize(13)
        font.setBold(self.root)
        p.setFont(font)
        text = self.node['title']
        # Two lines, with a tooltip for the full title.
        metrics = p.fontMetrics()
        lines, line = [], ''
        for char in text:
            if metrics.horizontalAdvance(line + char) > 151:
                lines.append(line)
                line = char
            else:
                line += char
        if line:
            lines.append(line)
        if len(lines) > 2:
            lines = lines[:2]
            lines[1] = metrics.elidedText(lines[1] + '…', Qt.TextElideMode.ElideRight, 151)
        p.drawText(QRectF(14, 10, 154, 40), Qt.AlignmentFlag.AlignVCenter, '\n'.join(lines))
        p.setFont(QFont(self.window.font().family(), 9))
        if self.root:
            meta = f'{len(self.window.forest.descendants(self.key))} 个步骤'
            p.setPen(QColor('#c5dec7'))
        else:
            wait = self.node.get('wait_until', 0)
            if wait > time.time():
                meta = f'等待 {max(1, int((wait - time.time() + 59) // 60))} 分钟'
                p.setPen(QColor('#ad8540'))
            else:
                meta = '现在可做' if self.ready else '后续步骤'
                p.setPen(QColor(GREEN if self.ready else MUTED))
            minutes = self.node.get('minutes', 0)
            meta += f'  ·  {minutes} 分钟' if minutes else '  ·  未估时'
        p.drawText(QRectF(14, 57, 178, 17), Qt.AlignmentFlag.AlignLeft, meta)
        p.setPen(QColor('#d7ead2' if self.root else '#6c9477'))
        p.setFont(QFont(self.window.font().family(), 19))
        p.drawText(QRectF(173, 12, 29, 30), Qt.AlignmentFlag.AlignCenter, '+')
        if self.node['children']:
            p.setFont(QFont(self.window.font().family(), 10))
            p.drawText(QRectF(175, 49, 28, 25), Qt.AlignmentFlag.AlignCenter,
                       '▸' if self.node.get('collapsed') else '▾')

    def hoverEnterEvent(self, event):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = event.screenPos()
            self.moved = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pressed is None or self.root or self.moved:
            return
        if (event.screenPos() - self.pressed).manhattanLength() < QApplication.startDragDistance():
            return
        self.moved = True
        drag = QDrag(self.window.view)
        mime = QMimeData()
        mime.setData(MIME, self.key.encode())
        drag.setMimeData(mime)
        pix = QPixmap(CARD_W + 6, CARD_H + 6)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.translate(3, 3)
        self.paint(painter, None)
        painter.end()
        drag.setPixmap(pix)
        drag.setHotSpot(event.pos().toPoint())
        self.window.message('拖到节点中间：接为后续；上 / 下边缘：调整同层顺序；左侧类别：跨类移动')
        drag.exec(Qt.DropAction.MoveAction)
        self.window.view.clear_drop()
        self.pressed = None

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pressed is not None and not self.moved:
            pos = event.pos()
            if pos.x() >= 170 and pos.y() < 49:
                self.window.add_menu(self.key, event.screenPos())
            elif pos.x() >= 170 and self.node['children']:
                self.window.perform(lambda: self.window.forest.edit(self.key, collapsed=not self.node.get('collapsed', False)))
            elif not self.root:
                self.window.complete(self.key)
        self.pressed = None
        event.accept()

    def contextMenuEvent(self, event):
        self.window.node_menu(self.key, event.screenPos())
        event.accept()


class ForestView(QGraphicsView):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor('#f7f9f5'))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setAcceptDrops(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.cards = {}
        self.drop_target = None
        self.drop_hint = None

    def drawBackground(self, p, rect):
        super().drawBackground(p, rect)
        p.setPen(QPen(QColor('#e2e8dc'), 1))
        step = 24
        for x in range(int(rect.left()) // step * step, int(rect.right()) + step, step):
            for y in range(int(rect.top()) // step * step, int(rect.bottom()) + step, step):
                p.drawPoint(QPointF(x, y))

    def render_forest(self):
        self.drop_hint = None
        self.drop_target = None
        self.scene().clear()
        self.cards = {}
        model = self.window.forest
        ready = {key for _, key in model.ready()}
        roots = model.data['roots']
        if self.window.selected in roots:
            roots = [self.window.selected]
        y_cursor = 28

        def height(key):
            n = model.nodes[key]
            if not n['children'] or n.get('collapsed'):
                return ROW
            return max(ROW, sum(height(child) for child in n['children']))

        def draw(key, depth, top):
            h = height(key)
            card = Card(self.window, key, key in ready)
            card.setPos(28 + depth * COL, top + (h - CARD_H) / 2)
            self.scene().addItem(card)
            self.cards[key] = card
            child_top = top
            if not model.nodes[key].get('collapsed'):
                for child in model.nodes[key]['children']:
                    other = draw(child, depth + 1, child_top)
                    start = card.pos() + QPointF(CARD_W, CARD_H / 2)
                    end = other.pos() + QPointF(0, CARD_H / 2)
                    path = QPainterPath(start)
                    path.cubicTo(start + QPointF(35, 0), end - QPointF(35, 0), end)
                    edge = self.scene().addPath(path, QPen(QColor('#c0d1ba'), 2))
                    edge.setZValue(-1)
                    child_top += height(child)
            return card

        for root in roots:
            draw(root, 0, y_cursor)
            y_cursor += height(root) + 38
        if not roots:
            title = self.scene().addText('先种下一棵任务树', QFont(self.window.font().family(), 22))
            title.setDefaultTextColor(QColor(GREEN))
            title.setPos(50, 80)
            hint = self.scene().addText('点击「＋ 新类别」，再从树干的 ＋ 开始拆步骤。\n也可以在「更多」中载入示例，试试点击和拖动。')
            hint.setDefaultTextColor(QColor(MUTED))
            hint.setPos(50, 140)
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-20, -20, 80, 70))

    def clear_drop(self):
        if self.drop_hint is not None:
            self.scene().removeItem(self.drop_hint)
            self.drop_hint = None
        self.drop_target = None

    def locate_drop(self, event):
        try:
            key = bytes(event.mimeData().data(MIME)).decode()
        except UnicodeError:
            return None
        scene_pos = self.mapToScene(event.position().toPoint())
        for target, card in self.cards.items():
            local = card.mapFromScene(scene_pos)
            if QRectF(0, 0, CARD_W, CARD_H).contains(local):
                mode = 'child' if card.root else ('before' if local.y() < 20 else 'after' if local.y() > CARD_H - 20 else 'child')
                if self.window.forest.can_move(key, target, mode):
                    return key, target, mode
        return None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.clear_drop()
        target = self.locate_drop(event)
        if target:
            key, dest, mode = target
            card = self.cards[dest]
            if mode == 'child':
                rect = QRectF(card.x() - 3, card.y() - 3, CARD_W + 6, CARD_H + 6)
                self.drop_hint = self.scene().addRect(rect, QPen(QColor('#5f9e75'), 3), QBrush(QColor(90, 160, 110, 35)))
            else:
                y = card.y() - 5 if mode == 'before' else card.y() + CARD_H + 5
                self.drop_hint = self.scene().addLine(card.x(), y, card.x() + CARD_W, y, QPen(QColor('#5f9e75'), 4))
            self.drop_hint.setZValue(5)
            self.drop_target = target
            self.window.message({'child': '松开：接为这个节点的后续分支', 'before': '松开：移到这个节点前面（同层）', 'after': '松开：移到这个节点后面（同层）'}[mode])
            event.acceptProposedAction()
        else:
            event.ignore()
        # Scroll horizontally and vertically when dragging near viewport edges.
        pos = event.position()
        for bar, coordinate, limit in ((self.horizontalScrollBar(), pos.x(), self.viewport().width()),
                                       (self.verticalScrollBar(), pos.y(), self.viewport().height())):
            if coordinate < 32:
                bar.setValue(bar.value() - 18)
            elif coordinate > limit - 32:
                bar.setValue(bar.value() + 18)

    def dragLeaveEvent(self, event):
        self.clear_drop()
        event.accept()

    def dropEvent(self, event):
        target = self.locate_drop(event)
        self.clear_drop()
        if target:
            self.window.perform(lambda: self.window.forest.move(*target), '已移动分支，可按 Ctrl+Z 撤销')
            event.acceptProposedAction()
        else:
            event.ignore()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.12 if event.angleDelta().y() > 0 else 1 / 1.12)
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom(self, scale):
        current = self.transform().m11()
        target = min(1.7, max(.35, current * scale))
        self.scale(target / current, target / current)

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1:
            self.resetTransform()
        if self.transform().m11() < .35:
            self.resetTransform()
            self.scale(.35, .35)


class CategoryList(QListWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def show_menu(self, pos):
        item = self.itemAt(pos)
        if item and item.data(Qt.ItemDataRole.UserRole):
            self.window.node_menu(item.data(Qt.ItemDataRole.UserRole), self.viewport().mapToGlobal(pos))

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        try:
            key = bytes(event.mimeData().data(MIME)).decode()
        except UnicodeError:
            event.ignore()
            return
        if item and self.window.forest.can_move(key, item.data(Qt.ItemDataRole.UserRole), 'child'):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if not item:
            event.ignore()
            return
        try:
            key = bytes(event.mimeData().data(MIME)).decode()
        except UnicodeError:
            event.ignore()
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        if self.window.forest.can_move(key, target, 'child'):
            self.window.perform(lambda: self.window.forest.move(key, target), '已移动到该类别')
            event.acceptProposedAction()
        else:
            event.ignore()


class Window(QMainWindow):
    def __init__(self, forest, tray_enabled=True):
        super().__init__()
        self.forest = forest
        self.selected = None
        self.quitting = False
        self.notified = set()
        self.settings = QSettings()
        self.setWindowTitle('枝序 · Task Grove')
        self.setWindowIcon(icon())
        self.resize(1000, 720)
        self.setMinimumSize(760, 550)
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        self.build_ui()
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('枝序 · 下一步，慢慢来')
        tray_menu = QMenu(self)
        tray_menu.addAction('打开 / 收起任务树', self.toggle)
        tray_menu.addAction('新增任务类别', self.new_category)
        tray_menu.addSeparator()
        tray_menu.addAction('退出枝序', self.quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason: self.toggle() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.messageClicked.connect(self.reveal)
        if tray_enabled:
            self.tray.show()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(15000)
        for sequence, callback in [('Ctrl+Z', lambda: self.perform(self.forest.undo, '已撤销')),
                                   ('Ctrl+Shift+Z', lambda: self.perform(self.forest.redo, '已重做')),
                                   ('Ctrl+N', self.new_task), ('Ctrl+Shift+N', self.new_category),
                                   ('Ctrl+F', self.search.setFocus), ('Escape', self.hide_to_tray)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        if forest.recovery:
            QTimer.singleShot(0, lambda: QMessageBox.information(self, '数据恢复', forest.recovery))

    def build_ui(self):
        host = QWidget()
        self.setCentralWidget(host)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(180)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 28, 16, 18)
        brand = QLabel('枝序')
        brand.setObjectName('brand')
        side.addWidget(brand)
        eyebrow = QLabel('TASK GROVE  /  下一步，慢慢来')
        eyebrow.setObjectName('eyebrow')
        eyebrow.setWordWrap(True)
        side.addWidget(eyebrow)
        side.addSpacing(28)
        label = QLabel('我的任务树')
        label.setObjectName('muted')
        side.addWidget(label)
        self.categories = CategoryList(self)
        self.categories.currentItemChanged.connect(self.select_category)
        side.addWidget(self.categories, 1)
        side.addWidget(button('＋ 新类别', self.new_category))
        side.addSpacing(12)
        self.count_label = QLabel()
        self.count_label.setObjectName('muted')
        side.addWidget(self.count_label)
        side.addWidget(button('使用说明 / 更多', self.more_menu))
        layout.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(24, 24, 22, 12)
        content.setSpacing(10)
        top = QHBoxLayout()
        self.heading = QLabel('所有任务树')
        self.heading.setObjectName('heading')
        top.addWidget(self.heading, 1)
        self.undo_button = button('↶ 撤销', lambda: self.perform(self.forest.undo, '已撤销'))
        top.addWidget(self.undo_button)
        top.addWidget(button('＋ 小任务', self.new_task, True))
        content.addLayout(top)
        sub = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('查找一个步骤…  Ctrl+F')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.find_task)
        sub.addWidget(self.search, 1)
        for text, callback in [('−', lambda: self.view.zoom(1 / 1.15)), ('＋', lambda: self.view.zoom(1.15)),
                               ('适应', lambda: self.view.fit())]:
            sub.addWidget(button(text, callback))
        content.addLayout(sub)
        help_text = QLabel('点击任务完成  ·  ＋ 拆分或插入  ·  拖动调整树枝  ·  右键更多')
        help_text.setObjectName('muted')
        content.addWidget(help_text)
        self.view = ForestView(self)
        content.addWidget(self.view, 1)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet('color: #e0e7da;')
        content.addWidget(divider)
        ready_top = QHBoxLayout()
        self.ready_label = QLabel('这段空档，可以做什么？')
        self.ready_label.setStyleSheet('font-weight: 600;')
        ready_top.addWidget(self.ready_label, 1)
        self.time_filter = QComboBox()
        for title, value in [('不限时长', 0), ('5 分钟内', 5), ('10 分钟内', 10), ('15 分钟内', 15), ('30 分钟内', 30), ('1 小时内', 60)]:
            self.time_filter.addItem(title, value)
        self.time_filter.currentIndexChanged.connect(self.refresh_ready)
        ready_top.addWidget(self.time_filter)
        content.addLayout(ready_top)
        self.ready_list = QListWidget()
        self.ready_list.setObjectName('ready')
        self.ready_list.setFixedHeight(136)
        content.addWidget(self.ready_list)
        self.status = QLabel('任务只保存在这台电脑上 · 改动自动保存')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        content.addWidget(self.status)
        layout.addLayout(content, 1)

    def message(self, text):
        self.status.setText(text)

    def perform(self, callback, text='已保存 · Ctrl+Z 可撤销'):
        try:
            result = callback()
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            QMessageBox.warning(self, '这次操作未保存', str(error))
            return None
        self.message(text)
        # Do not destroy a graphics item in its own mouse/drag handler.
        QTimer.singleShot(0, self.refresh)
        return result

    def refresh(self):
        if self.selected not in self.forest.data['roots']:
            self.selected = None
        self.categories.blockSignals(True)
        self.categories.clear()
        all_item = QListWidgetItem('◉  所有任务树')
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self.categories.addItem(all_item)
        selected_item = all_item
        for root in self.forest.data['roots']:
            node = self.forest.nodes[root]
            item = QListWidgetItem('○  ' + node['title'])
            item.setToolTip(node['title'] + '\n拖入任务可移到此类别；右键编辑')
            item.setData(Qt.ItemDataRole.UserRole, root)
            self.categories.addItem(item)
            if root == self.selected:
                selected_item = item
        self.categories.setCurrentItem(selected_item)
        self.categories.blockSignals(False)
        self.heading.setText(self.forest.nodes[self.selected]['title'] if self.selected else '所有任务树')
        self.count_label.setText(f'{len(self.forest.data["roots"])} 棵树 · {sum(n["kind"] == "task" for n in self.forest.nodes.values())} 个步骤')
        self.undo_button.setEnabled(bool(self.forest.undo_stack))
        self.view.render_forest()
        self.refresh_ready()

    def select_category(self, current, previous):
        self.selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.heading.setText(self.forest.nodes[self.selected]['title'] if self.selected in self.forest.nodes else '所有任务树')
        self.view.render_forest()
        self.view.resetTransform()
        self.view.horizontalScrollBar().setValue(0)
        self.view.verticalScrollBar().setValue(0)
        self.refresh_ready()

    def refresh_ready(self):
        self.ready_list.clear()
        tasks = self.forest.ready(self.time_filter.currentData() or 0)
        if self.selected:
            tasks = [(root, key) for root, key in tasks if root == self.selected]
        self.ready_label.setText(f'这段空档，可以做什么？  ·  {len(tasks)} 项')
        for root, key in tasks:
            node = self.forest.nodes[key]
            item = QListWidgetItem()
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(10, 4, 6, 4)
            title = QLabel(node['title'])
            title.setToolTip(node['title'])
            title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            box.addWidget(title, 1)
            meta = QLabel(f'{self.forest.nodes[root]["title"][:12]} · ' + (f'{node["minutes"]} 分钟' if node['minutes'] else '未估时'))
            meta.setObjectName('muted')
            box.addWidget(meta)
            done = button('✓', lambda checked=False, k=key: self.complete(k))
            done.setToolTip('完成这个任务，后续步骤会自动接上')
            box.addWidget(done)
            locate = button('定位', lambda checked=False, k=key: self.locate(k))
            box.addWidget(locate)
            item.setSizeHint(row.sizeHint())
            self.ready_list.addItem(item)
            self.ready_list.setItemWidget(item, row)
        if not tasks:
            self.ready_list.addItem('没有符合条件的步骤。试试切换类别或放宽时长；有时长筛选时不含未估时任务。')

    def find_task(self, text):
        for card in self.view.cards.values():
            card.update()
        if text.strip():
            hits = [key for key, node in self.forest.nodes.items() if text.strip().casefold() in node['title'].casefold()]
            if hits:
                self.locate(hits[0])
                self.message(f'找到 {len(hits)} 个匹配步骤，树上以金色边框标记')
            else:
                self.message('没有找到这个步骤')

    def locate(self, key):
        root = self.forest.category(key)
        hidden = []
        parent = self.forest.parent(key)
        while parent:
            if self.forest.nodes[parent].get('collapsed'):
                hidden.append(parent)
            parent = self.forest.parent(parent)
        if hidden:
            self.perform(lambda: self.forest.change(lambda data: [data['nodes'][k].update(collapsed=False) for k in hidden]))
        if self.selected and self.selected != root:
            self.selected = root
        self.refresh()
        if key in self.view.cards:
            self.view.centerOn(self.view.cards[key])

    def new_category(self):
        self.reveal()
        dialog = TaskDialog(self, '种下一棵任务树', category=True)
        if dialog.exec():
            key = self.perform(lambda: self.forest.add(dialog.values()['title']), '已添加类别，从树干的 ＋ 开始添加步骤')
            if key:
                self.selected = key

    def new_task(self):
        roots = self.forest.data['roots']
        if not roots:
            self.new_category()
            return
        root = self.selected
        if root is None:
            menu = QMenu(self)
            for key in roots:
                menu.addAction(self.forest.nodes[key]['title'], lambda checked=False, k=key: self.add_task(k))
            menu.exec(self.mapToGlobal(self.rect().center()))
        else:
            self.add_task(root)

    def add_task(self, target, mode='child'):
        title = {'child': '添加后续分支', 'before': '在此前插入一步', 'after': '在此后插入一步', 'sibling': '添加同层并行任务'}[mode]
        dialog = TaskDialog(self, title)
        if dialog.exec():
            self.perform(lambda: self.forest.add(target=target, mode=mode, **dialog.values()))

    def add_menu(self, key, pos):
        menu = QMenu(self)
        menu.addAction('＋ 添加后续分支', lambda: self.add_task(key))
        if self.forest.nodes[key]['kind'] == 'task':
            menu.addAction('↑ 在此前插入一步', lambda: self.add_task(key, 'before'))
            menu.addAction('↓ 在此后插入一步', lambda: self.add_task(key, 'after'))
            menu.addAction('⑂ 添加同层并行任务', lambda: self.add_task(key, 'sibling'))
        menu.exec(pos)

    def complete(self, key):
        if key not in self.forest.nodes:
            return
        title = self.forest.nodes[key]['title']
        self.perform(lambda: self.forest.complete(key), f'已完成「{title[:35]}」 · 后续已接上 · Ctrl+Z 撤销')

    def node_menu(self, key, pos):
        if key not in self.forest.nodes:
            return
        node = self.forest.nodes[key]
        category = node['kind'] == 'category'
        menu = QMenu(self)
        if not category:
            menu.addAction('✓ 完成，保留后续分支', lambda: self.complete(key))
        menu.addAction('编辑名称 / 时间' if not category else '重命名类别', lambda: self.edit_task(key))
        add = menu.addMenu('＋ 添加或插入步骤')
        add.addAction('添加后续分支', lambda: self.add_task(key))
        if not category:
            for title, mode in [('在此前插入一步', 'before'), ('在此后插入一步', 'after'), ('同层并行任务', 'sibling')]:
                add.addAction(title, lambda checked=False, m=mode: self.add_task(key, m))
            wait = menu.addMenu('等待 / 暂放')
            for minutes in [5, 15, 30, 60]:
                wait.addAction(f'{minutes} 分钟后提醒', lambda checked=False, m=minutes: self.perform(lambda: self.forest.edit(key, wait_until=time.time() + m * 60)))
            wait.addAction('结束等待，现在可做', lambda: self.perform(lambda: self.forest.edit(key, wait_until=0)))
            move = menu.addMenu('移动到类别')
            for root in self.forest.data['roots']:
                move.addAction(self.forest.nodes[root]['title'], lambda checked=False, r=root: self.perform(lambda: self.forest.move(key, r)))
        if node['children']:
            menu.addAction('展开分支' if node.get('collapsed') else '收起分支',
                           lambda: self.perform(lambda: self.forest.edit(key, collapsed=not node.get('collapsed', False))))
        menu.addSeparator()
        menu.addAction('删除整棵树…' if category else '删除整条分支…', lambda: self.delete_branch(key))
        menu.exec(pos)

    def edit_task(self, key):
        node = self.forest.nodes[key]
        dialog = TaskDialog(self, '编辑类别' if node['kind'] == 'category' else '编辑任务', node, node['kind'] == 'category')
        if dialog.exec():
            self.perform(lambda: self.forest.edit(key, **dialog.values()))

    def delete_branch(self, key):
        count = 1 + len(self.forest.descendants(key))
        if QMessageBox.question(self, '删除分支', f'删除「{self.forest.nodes[key]["title"]}」及其后续？共 {count} 个节点。\n可用 Ctrl+Z 撤销。',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.forest.delete_branch(key))

    def more_menu(self):
        menu = QMenu(self)
        menu.addAction('使用说明', self.show_help)
        menu.addAction('导出任务备份…', self.export_data)
        menu.addAction('导入任务备份…', self.import_data)
        if not self.forest.nodes:
            menu.addAction('载入示例任务树', lambda: self.perform(self.forest.seed_example))
        auto = menu.addAction('登录桌面时自动启动')
        auto.setCheckable(True)
        auto.setChecked(desktop.AUTOSTART.exists())
        auto.triggered.connect(lambda enabled: self.perform(lambda: desktop.set_autostart(enabled), '已更新自启动设置'))
        pin = menu.addAction('窗口置顶')
        pin.setCheckable(True)
        pin.setChecked(bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        pin.triggered.connect(self.set_pinned)
        menu.addSeparator()
        menu.addAction('退出枝序', self.quit_app)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft() + QPointF(20, -30).toPoint()))

    def set_pinned(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def show_help(self):
        QMessageBox.information(self, '枝序 · 使用说明',
            '一类工作是一棵树，树枝从左向右表示先后步骤，同层分支可以并行。\n\n'
            '• 点击任务文字：完成并移除该步，后续步骤自动接到前面。\n'
            '• 点击 ＋ 或右键：新增分支，在某步前/后插入，添加并行任务。\n'
            '• 拖动任务：中间接为后续；上/下边缘调整同层顺序；拖到左侧类别可跨类移动。\n'
            '• 完成或移动会携带/接续整条分支；Ctrl+Z 撤销，Ctrl+Shift+Z 重做。\n'
            '• 右键设置等待，倒计时结束后通知，不会自动完成。\n'
            '• 下方只列出没有前置任务且不在等待中的步骤。限时筛选需要先填写预计时间。\n'
            '• Ctrl+滚轮缩放；拖动画布空白处平移；小箭头收起分支。\n'
            '• 关闭、最小化或 Esc 收到托盘；通过托盘或更多菜单退出。\n\n'
            f'任务自动保存在：{self.forest.path}\n'
            '前一次保存保存在 tasks.json.bak。首次使用可从更多菜单载入示例。')

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出备份', str(Path.home() / 'task-grove-backup.json'), 'JSON (*.json)')
        if path:
            self.perform(lambda: self.forest.export_file(path), '已导出备份')

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入备份', str(Path.home()), 'JSON (*.json)')
        if path and QMessageBox.question(self, '导入任务', '导入会替换当前任务树；可以 Ctrl+Z 撤销。继续？') == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.forest.import_file(path), '已导入任务，可按 Ctrl+Z 撤销')

    def tick(self):
        due = [(key, node) for key, node in self.forest.nodes.items()
               if node['kind'] == 'task' and 0 < node.get('wait_until', 0) <= time.time()
               and (key, node.get('wait_until')) not in self.notified]
        for key, node in due:
            self.notified.add((key, node['wait_until']))
        if due:
            titles = '、'.join(node['title'] for _, node in due)
            self.tray.showMessage('等待结束，可以回来看看', titles, QSystemTrayIcon.MessageIcon.Information, 8000)
            self.message('等待结束：' + titles)
        self.refresh_ready()
        ready = {key for _, key in self.forest.ready()}
        for key, card in self.view.cards.items():
            card.ready = key in ready
            card.update()

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle(self):
        self.hide() if self.isVisible() and not self.isMinimized() else self.reveal()

    def hide_to_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            self.settings.setValue('geometry', self.saveGeometry())
            self.hide()
        else:
            self.showMinimized()

    def closeEvent(self, event):
        self.settings.setValue('geometry', self.saveGeometry())
        if self.quitting:
            event.accept()
        elif QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            # Keep a taskbar entry if the desktop has no system tray.
            event.ignore()
            self.showMinimized()

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
                QTimer.singleShot(0, self.hide)

    def quit_app(self):
        self.quitting = True
        self.settings.setValue('geometry', self.saveGeometry())
        self.tray.hide()
        QApplication.instance().quit()


def main():
    parser = argparse.ArgumentParser(description='枝序 · 本地桌面任务树')
    parser.add_argument('--background', action='store_true', help='登录启动时收在托盘')
    parser.add_argument('--data-dir', type=Path, help='单独的数据目录（可用于测试）')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('task-grove')
    app.setOrganizationName('TaskGrove')
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icon())
    app.setFont(QFont('Noto Sans CJK SC', 10))
    app.setStyleSheet(STYLE)
    folder = args.data_dir or desktop.DATA / 'task-grove'
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        QMessageBox.critical(None, '无法打开任务目录', str(error))
        return 1
    name = 'task-grove-' + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:20]
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(600):
        socket.write(b'show')
        socket.waitForBytesWritten(600)
        socket.disconnectFromServer()
        return 0
    lock = QLockFile(str(folder / 'instance.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, '枝序已在运行', '已有实例正在使用任务数据，请从托盘打开它。')
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    if not server.listen(name):
        QMessageBox.critical(None, '无法启动', server.errorString())
        return 1
    try:
        forest = Forest(folder / 'tasks.json')
    except (OSError, ValueError, TypeError, RecursionError) as error:
        QMessageBox.critical(None, '无法读取任务数据', str(error))
        return 1
    window = Window(forest)

    def incoming():
        connection = server.nextPendingConnection()
        if connection:
            connection.readyRead.connect(lambda: connection.readAll())
            connection.disconnected.connect(connection.deleteLater)
        window.reveal()

    server.newConnection.connect(incoming)
    if not args.background:
        window.reveal()
    else:
        # GNOME's tray may register after autostart; allow it time to appear.
        QTimer.singleShot(8000, lambda: window.reveal() if not QSystemTrayIcon.isSystemTrayAvailable() else None)
    result = app.exec()
    server.close()
    lock.unlock()
    return result


if __name__ == '__main__':
    sys.exit(main())
