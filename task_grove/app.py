"""Native Qt desktop UI. Run with python -m task_grove.app."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import (Qt, QPointF, QRectF, QTimer, QMimeData, QSettings,
                            QLockFile, QStandardPaths, QDateTime)
from PySide6.QtGui import (QAction, QColor, QPainter, QPen, QBrush, QFont, QPalette,
                           QPainterPath, QIcon, QPixmap, QDrag, QKeySequence, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QListWidget,
    QListWidgetItem, QGraphicsView, QGraphicsScene, QGraphicsObject, QMenu,
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QMessageBox,
    QFileDialog, QSystemTrayIcon, QFrame, QAbstractItemView, QSizePolicy,
    QCheckBox, QDateTimeEdit)

from .model import Forest, InvalidTree
from . import desktop
from .input_method import configure_input_method, capture_input_mode, restore_input_mode
from .reminders import Reminders, schedule_text

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
QLineEdit, QComboBox, QSpinBox, QDateTimeEdit { background: white; border: 1px solid #dce5db; border-radius: 7px; padding: 7px; }
QLineEdit:focus, QDateTimeEdit:focus { border: 1px solid #79a68d; }
QDateTimeEdit { color: #253e33; selection-background-color: #28664f; selection-color: white; padding-right: 28px; }
QDateTimeEdit:disabled { background: #edf1eb; color: #68766c; border-color: #d5dfd2; }
QDateTimeEdit::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 25px; background: #e7eee2; border-left: 1px solid #cbd9c8; border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
QDateTimeEdit::drop-down:disabled { background: #e5eae2; border-color: #d5dfd2; }
QCheckBox { spacing: 7px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #829b85; border-radius: 4px; background: white; }
QCheckBox::indicator:hover { border: 1px solid #28664f; background: #edf5e7; }
QCheckBox::indicator:checked { background: #28664f; border-color: #28664f; }
QCheckBox::indicator:checked:hover { background: #34795d; }
QCheckBox::indicator:disabled { background: #edf1eb; border-color: #cbd5c6; }
QCalendarWidget QWidget { background: #ffffff; color: #253e33; }
QCalendarWidget QToolButton { background: #e7eee2; color: #253e33; border: none; border-radius: 4px; padding: 5px; }
QCalendarWidget QAbstractItemView { background: white; color: #253e33; selection-background-color: #28664f; selection-color: white; alternate-background-color: #f3f6ef; }
QCalendarWidget QAbstractItemView:disabled { color: #9aa69c; }
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


STYLE += '\nQCheckBox::indicator:checked { image: url("' + (desktop.ROOT / 'assets/check.svg').as_posix() + '"); }'
STYLE += '\nQDateTimeEdit::down-arrow { width: 12px; height: 8px; image: url("' + (desktop.ROOT / 'assets/chevron-down.svg').as_posix() + '"); }'


def apply_theme(app):
    """Use one light palette for native, disabled, calendar and custom widgets."""
    app.setStyle('Fusion')
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: '#f7f9f5',
        QPalette.ColorRole.WindowText: INK,
        QPalette.ColorRole.Base: '#ffffff',
        QPalette.ColorRole.AlternateBase: '#edf2e9',
        QPalette.ColorRole.Text: INK,
        QPalette.ColorRole.Button: '#edf2e9',
        QPalette.ColorRole.ButtonText: INK,
        QPalette.ColorRole.Highlight: GREEN,
        QPalette.ColorRole.HighlightedText: '#ffffff',
        QPalette.ColorRole.ToolTipBase: INK,
        QPalette.ColorRole.ToolTipText: '#ffffff',
        QPalette.ColorRole.PlaceholderText: '#758679',
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor('#68766c'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor('#edf1eb'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor('#e5eae2'))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


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
    def __init__(self, parent, title, node=None, category=False, inbox=False):
        self.input_mode = capture_input_mode()
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.category = category
        self.operation = 'save'
        self.original = node or {}
        form = QFormLayout(self)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(14)
        self.name = QLineEdit(self.original.get('title', ''))
        self.name.setMaxLength(200)
        self.name.setPlaceholderText('写下一个具体、能开始的动作')
        self.name.setReadOnly(inbox)
        form.addRow('名称', self.name)
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 1440)
        self.minutes.setSpecialValueText('未估时')
        self.minutes.setSuffix(' 分钟')
        self.minutes.setValue(self.original.get('minutes', 0))
        self.time_inputs = {}
        self.time_dirty = set()
        if not category:
            form.addRow('预计用时', self.minutes)
            for field, label in (('start_at', '开始时间'), ('due_at', '截止时间')):
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                check = QCheckBox('指定')
                stamp = self.original.get(field, 0)
                check.setChecked(bool(stamp))
                editor = QDateTimeEdit()
                editor.setCalendarPopup(True)
                editor.setDisplayFormat('yyyy-MM-dd HH:mm')
                editor.setDateTime(QDateTime.fromSecsSinceEpoch(int(stamp or time.time() + 3600)))
                editor.setEnabled(bool(stamp))
                check.toggled.connect(editor.setEnabled)
                check.toggled.connect(lambda checked, f=field: self.time_dirty.add(f))
                editor.dateTimeChanged.connect(lambda value, f=field: self.time_dirty.add(f))
                layout.addWidget(check)
                layout.addWidget(editor, 1)
                self.time_inputs[field] = check, editor
                form.addRow(label, row)
            hint = QLabel('指定任一时间即进入「已定时任务」。\n提前 1 小时、10 分钟及到时提醒；步骤可以跳着做。')
            hint.setObjectName('muted')
            form.addRow(hint)
        if node:
            operations = QHBoxLayout()
            if not category:
                operations.addWidget(button('✓ 完成此任务', lambda: self.finish('complete')))
                operations.addWidget(button('删除此节点', lambda: self.finish('remove')))
            delete = button('删除整棵树…' if category else '删除整条分支…', lambda: self.finish('branch'))
            delete.setEnabled(not inbox)
            operations.addWidget(delete)
            form.addRow(operations)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText('保存')
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        self.name.textChanged.connect(lambda text: actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip())))
        actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.name.text().strip()))
        form.addRow(actions)
        self.name.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        restore_input_mode(self.input_mode, self)

    def done(self, result):
        mode = capture_input_mode()
        parent = self.parentWidget()
        super().done(result)
        if parent is not None:
            restore_input_mode(mode, parent)

    def finish(self, operation):
        self.operation = operation
        super().accept()

    def accept(self):
        values = self.values()
        if values.get('start_at') and values.get('due_at') and values['due_at'] < values['start_at']:
            QMessageBox.warning(self, '时间需要调整', '截止时间不能早于开始时间。')
            return
        if self.name.text().strip():
            super().accept()

    def values(self):
        values = dict(title=self.name.text().strip(), minutes=self.minutes.value())
        for field, (check, editor) in self.time_inputs.items():
            values[field] = (editor.dateTime().toSecsSinceEpoch() if field in self.time_dirty else self.original.get(field, 0)) if check.isChecked() else 0
        return values


class Card(QGraphicsObject):
    def __init__(self, window, key):
        super().__init__()
        self.window, self.key = window, key
        self.node = window.forest.nodes[key]
        self.root = self.node['kind'] == 'category'
        self.hover = False
        self.pressed = None
        self.moved = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(self.node['title'] + '\n' + ('点击 ＋ 添加步骤；右键编辑分类' if self.root else
            '左键选中并拖动 · 勾选完成 · 右键直接编辑\n' + schedule_text(self.node)))

    def boundingRect(self):
        return QRectF(-3, -3, CARD_W + 6, CARD_H + 6)

    def paint(self, p, option, widget=None):
        if self.key not in self.window.forest.nodes:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        query = self.window.search.text().strip().casefold()
        matched = query and query in self.node['title'].casefold()
        fill = GREEN if self.root else ('#f0f6e9' if self.hover else '#ffffff')
        border = '#28664f' if self.key == self.window.selected_node else '#d7e3d3'
        if matched:
            border = '#e2a43d'
        p.setPen(QPen(QColor(border), 2 if self.hover or matched or self.key == self.window.selected_node else 1))
        p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(0, 0, CARD_W, CARD_H), 13, 13)
        color = '#ffffff' if self.root else INK
        p.setPen(QColor(color))
        font = QFont(self.window.font())
        font.setPixelSize(13)
        font.setBold(self.root)
        p.setFont(font)
        text = self.node['title']
        text_x = 14 if self.root else 40
        text_width = 154 if self.root else 128
        if not self.root:
            p.setBrush(QColor('#ffffff'))
            p.setPen(QPen(QColor('#7b9e83'), 1.4))
            p.drawRoundedRect(QRectF(13, 23, 18, 18), 4, 4)
            if self.hover:
                p.drawText(QRectF(13, 20, 18, 22), Qt.AlignmentFlag.AlignCenter, '✓')
            p.setPen(QColor(color))
        # Two lines, with a tooltip for the full title.
        metrics = p.fontMetrics()
        lines, line = [], ''
        for char in text:
            if metrics.horizontalAdvance(line + char) > text_width:
                lines.append(line)
                line = char
            else:
                line += char
        if line:
            lines.append(line)
        if len(lines) > 2:
            lines = lines[:2]
            lines[1] = metrics.elidedText(lines[1] + '…', Qt.TextElideMode.ElideRight, text_width)
        p.drawText(QRectF(text_x, 10, text_width, 40), Qt.AlignmentFlag.AlignVCenter, '\n'.join(lines))
        p.setFont(QFont(self.window.font().family(), 9))
        if self.root:
            meta = f'{len(self.window.forest.descendants(self.key))} 个步骤'
            p.setPen(QColor('#c5dec7'))
        else:
            minutes = self.node.get('minutes', 0)
            meta = f'{minutes} 分钟' if minutes else '未估时'
            if self.node.get('due_at'):
                meta = '截止 ' + QDateTime.fromSecsSinceEpoch(int(self.node['due_at'])).toString('MM-dd HH:mm')
            elif self.node.get('start_at'):
                meta = '开始 ' + QDateTime.fromSecsSinceEpoch(int(self.node['start_at'])).toString('MM-dd HH:mm')
            p.setPen(QColor(MUTED))
        p.drawText(QRectF(14, 57, 178, 17), Qt.AlignmentFlag.AlignLeft, meta)
        p.setPen(QColor('#d7ead2' if self.root else '#6c9477'))
        p.setFont(QFont(self.window.font().family(), 19))
        p.drawText(QRectF(173, 12, 29, 30), Qt.AlignmentFlag.AlignCenter, '+')
        if self.node['children']:
            p.setFont(QFont(self.window.font().family(), 10))
            p.drawText(QRectF(175, 49, 28, 25), Qt.AlignmentFlag.AlignCenter,
                       '▸' if self.window.is_collapsed(self.key) else '▾')

    def hoverEnterEvent(self, event):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = event.screenPos()
            self.press_local = event.pos()
            self.window.select_node(self.key)
            self.moved = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pressed is None or self.root or self.moved or self.press_local.x() >= 170 or self.press_local.x() <= 36:
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
                self.window.toggle_branch(self.key)
            elif not self.root and QRectF(10, 19, 25, 27).contains(pos):
                self.window.complete(self.key)
        self.pressed = None
        event.accept()

    def contextMenuEvent(self, event):
        self.window.edit_task(self.key)
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
        roots = model.data['roots']
        if self.window.selected in roots:
            roots = [self.window.selected]
        y_cursor = 28

        def height(key):
            n = model.nodes[key]
            if not n['children'] or self.window.is_collapsed(key):
                return ROW
            return max(ROW, sum(height(child) for child in n['children']))

        def draw(key, depth, top):
            h = height(key)
            card = Card(self.window, key)
            card.setPos(28 + depth * COL, top + (h - CARD_H) / 2)
            self.scene().addItem(card)
            self.cards[key] = card
            child_top = top
            if not self.window.is_collapsed(key):
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

    def contextMenuEvent(self, event):
        position = self.mapToScene(event.pos())
        for key, card in self.cards.items():
            if QRectF(0, 0, CARD_W, CARD_H).contains(card.mapFromScene(position)):
                self.window.edit_task(key)
                event.accept()
                return
        super().contextMenuEvent(event)

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
            self.window.edit_task(item.data(Qt.ItemDataRole.UserRole))

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
        self.selected_node = None
        self.overview_expanded = set()
        self.reminders = Reminders(forest.path.with_name('reminders.json'))
        self.quitting = False
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
        self.timer.start(10000)
        if tray_enabled:
            QTimer.singleShot(2500, self.tick)
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
        side.addWidget(button('＋ 新类别', self.new_category))
        side.addWidget(self.categories, 1)
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
        help_text = QLabel('左键选中 / 拖动  ·  勾选完成  ·  右键编辑  ·  ＋ 添加或插入')
        help_text.setObjectName('muted')
        content.addWidget(help_text)
        self.view = ForestView(self)
        content.addWidget(self.view, 1)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet('color: #e0e7da;')
        content.addWidget(divider)
        ready_top = QHBoxLayout()
        self.ready_label = QLabel('已定时任务')
        self.ready_label.setStyleSheet('font-weight: 600;')
        ready_top.addWidget(self.ready_label, 1)
        self.time_filter = QComboBox()
        for title, value in [('全部定时', 'all'), ('今日任务', 'today'), ('已逾期', 'overdue')]:
            self.time_filter.addItem(title, value)
        self.time_filter.currentIndexChanged.connect(self.refresh_scheduled)
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
        self.refresh_scheduled()

    def select_category(self, current, previous):
        self.selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        if self.selected is None:
            self.overview_expanded.clear()
        self.heading.setText(self.forest.nodes[self.selected]['title'] if self.selected in self.forest.nodes else '所有任务树')
        self.view.render_forest()
        self.view.resetTransform()
        self.view.horizontalScrollBar().setValue(0)
        self.view.verticalScrollBar().setValue(0)
        self.refresh_scheduled()

    def refresh_scheduled(self):
        scroll = self.ready_list.verticalScrollBar().value()
        self.ready_list.clear()
        tasks = self.forest.scheduled(self.time_filter.currentData() or 'all')
        self.ready_label.setText(f'已定时任务  ·  {len(tasks)} 项')
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
            meta = QLabel(schedule_text(node))
            meta.setToolTip(self.forest.nodes[root]['title'] + '\n' + schedule_text(node))
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
            self.ready_list.addItem('暂无定时任务。右键编辑任一任务，指定开始时间或截止时间。')
        self.ready_list.verticalScrollBar().setValue(scroll)

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
        self.selected = root
        self.selected_node = key
        self.refresh()
        if key in self.view.cards:
            self.view.centerOn(self.view.cards[key])

    def new_category(self):
        if not self.isVisible():
            self.reveal()
        dialog = TaskDialog(self, '种下一棵任务树', category=True)
        if dialog.exec():
            key = self.perform(lambda: self.forest.add(dialog.values()['title']), '已添加类别，从树干的 ＋ 开始添加步骤')
            if key:
                self.selected = key

    def new_task(self):
        roots = self.forest.data['roots']
        if not roots:
            return
        root = self.selected
        self.add_task(root or self.forest.inbox)

    def add_task(self, target, mode='child', input_mode=None):
        title = {'child': '添加后续分支', 'before': '在此前插入一步', 'after': '在此后插入一步', 'sibling': '添加同层并行任务'}[mode]
        dialog = TaskDialog(self, title)
        if input_mode is not None:
            dialog.input_mode = input_mode
        if dialog.exec():
            key = self.perform(lambda: self.forest.add(target=target, mode=mode, **dialog.values()))
            if key:
                self.selected = self.forest.category(key)
                self.selected_node = key

    def add_menu(self, key, pos):
        input_mode = capture_input_mode()
        menu = QMenu(self)
        menu.addAction('＋ 添加后续分支', lambda: self.add_task(key, input_mode=input_mode))
        if self.forest.nodes[key]['kind'] == 'task':
            menu.addAction('↑ 在此前插入一步', lambda: self.add_task(key, 'before', input_mode))
            menu.addAction('↓ 在此后插入一步', lambda: self.add_task(key, 'after', input_mode))
            menu.addAction('⑂ 添加同层并行任务', lambda: self.add_task(key, 'sibling', input_mode))
        menu.exec(pos)

    def complete(self, key):
        if key not in self.forest.nodes:
            return
        title = self.forest.nodes[key]['title']
        self.perform(lambda: self.forest.complete(key), f'已完成「{title[:35]}」 · 后续已接上 · Ctrl+Z 撤销')

    def edit_task(self, key):
        if key not in self.forest.nodes:
            return
        self.select_node(key)
        node = self.forest.nodes[key]
        dialog = TaskDialog(self, '编辑类别' if node['kind'] == 'category' else '编辑任务', node,
                            node['kind'] == 'category', key == self.forest.inbox)
        if dialog.exec():
            if dialog.operation in ('complete', 'remove'):
                self.complete(key)
            elif dialog.operation == 'branch':
                self.delete_branch(key)
            else:
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
        if not any(n['kind'] == 'task' for n in self.forest.nodes.values()):
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
            '一类工作是一棵树，步骤可以跳着做。零散任务是常驻收纳树。\n\n'
            '• 左键选择并拖动节点，勾选方框完成；后续分支自动接上。\n'
            '• 右键直接打开编辑页，可以改名、定时、完成或删除。\n'
            '• 点击 ＋ 添加后续、在前后插入或添加同层任务。\n'
            '• 拖到中间接为后续；上/下边缘同层重排；左侧类别跨类移动。\n'
            '• 指定开始/截止时间后进入底部「已定时任务」。\n'
            '• 提前 1 小时、10 分钟及到时提醒；开机汇总今日未完成任务。\n'
            '• 所有任务树默认收起步骤；点击小箭头或左侧类别展开。\n'
            '• Ctrl+Z 撤销，Ctrl+Shift+Z 重做；Ctrl+滚轮缩放。\n'
            '• 关闭、最小化或 Esc 收到托盘，通过更多菜单退出。\n\n'
            f'数据自动保存在：{self.forest.path}\n')

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出备份', str(Path.home() / 'task-grove-backup.json'), 'JSON (*.json)')
        if path:
            self.perform(lambda: self.forest.export_file(path), '已导出备份')

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入备份', str(Path.home()), 'JSON (*.json)')
        if path and QMessageBox.question(self, '导入任务', '导入会替换当前任务树；可以 Ctrl+Z 撤销。继续？') == QMessageBox.StandardButton.Yes:
            self.perform(lambda: self.forest.import_file(path), '已导入任务，可按 Ctrl+Z 撤销')

    def select_node(self, key):
        old = self.selected_node
        self.selected_node = key
        for item in (old, key):
            if item in self.view.cards:
                self.view.cards[item].update()

    def is_collapsed(self, key):
        if self.selected is None and self.forest.nodes[key]['kind'] == 'category':
            return key not in self.overview_expanded
        return self.forest.nodes.get(key, {}).get('collapsed', False)

    def toggle_branch(self, key):
        if self.selected is None and self.forest.nodes[key]['kind'] == 'category':
            if key in self.overview_expanded:
                self.overview_expanded.remove(key)
            else:
                self.overview_expanded.add(key)
            QTimer.singleShot(0, self.view.render_forest)
        else:
            self.perform(lambda: self.forest.edit(key, collapsed=not self.is_collapsed(key)))

    def notify(self, title, body):
        import shutil
        import subprocess
        sender = shutil.which('notify-send')
        if sender:
            subprocess.Popen([sender, '--app-name=枝序', '--icon=' + str(desktop.ROOT / 'assets/icon.svg'), title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 10000)
        self.message(title + ' · ' + body.replace('\n', ' · '))

    def tick(self):
        try:
            self.reminders.poll(self.forest, self.notify)
        except OSError as error:
            self.message('提醒记录未保存：' + str(error))
        self.refresh_scheduled()
        for card in self.view.cards.values():
            card.update()

    def reveal(self):
        mode = capture_input_mode()
        if self.isMinimized():
            if self.settings.value('maximized', False, type=bool):
                self.showMaximized()
            else:
                self.showNormal()
        elif not self.isVisible():
            self.showMaximized() if self.settings.value('maximized', False, type=bool) else self.show()
        self.raise_()
        self.activateWindow()
        restore_input_mode(mode, self)

    def toggle(self):
        self.hide() if self.isVisible() and not self.isMinimized() else self.reveal()

    def hide_to_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            self.settings.setValue('geometry', self.saveGeometry())
            self.settings.setValue('maximized', self.isMaximized() or bool(self.windowState() & Qt.WindowState.WindowMaximized))
            self.hide()
        else:
            self.showMinimized()

    def closeEvent(self, event):
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('maximized', self.isMaximized() or bool(self.windowState() & Qt.WindowState.WindowMaximized))
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
        self.settings.setValue('maximized', self.isMaximized() or bool(self.windowState() & Qt.WindowState.WindowMaximized))
        self.tray.hide()
        QApplication.instance().quit()


def main():
    parser = argparse.ArgumentParser(description='枝序 · 本地桌面任务树')
    parser.add_argument('--background', action='store_true', help='登录启动时收在托盘')
    parser.add_argument('--data-dir', type=Path, help='单独的数据目录（可用于测试）')
    args = parser.parse_args()
    configure_input_method()
    app = QApplication(sys.argv[:1])
    app.setApplicationName('task-grove')
    app.setOrganizationName('TaskGrove')
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icon())
    app.setFont(QFont('Noto Sans CJK SC', 10))
    apply_theme(app)
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
