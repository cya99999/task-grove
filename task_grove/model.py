"""Ordered task forest, independent of Qt. All mutations are validated and atomic."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid


class InvalidTree(ValueError):
    pass


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise InvalidTree('不支持的数据格式（需要 version 1）')
    nodes, roots = data.get('nodes'), data.get('roots')
    if not isinstance(nodes, dict) or not isinstance(roots, list) or len(nodes) > 10000:
        raise InvalidTree('任务数据不完整或节点超过 10000 个')
    seen = set()

    def visit(key, depth):
        if not isinstance(key, str) or key not in nodes or key in seen or depth > 100:
            raise InvalidTree('存在循环、重复节点、失效分支或层级过深')
        seen.add(key)
        n = nodes[key]
        if not isinstance(n, dict):
            raise InvalidTree('节点格式错误')
        if n.get('kind') != ('category' if depth == 0 else 'task'):
            raise InvalidTree('分类只能位于树根')
        if not isinstance(n.get('title'), str) or not n['title'].strip() or len(n['title']) > 200:
            raise InvalidTree('任务名称应为 1–200 个字符')
        if not isinstance(n.get('children'), list):
            raise InvalidTree('分支列表格式错误')
        minutes = n.get('minutes', 0)
        waiting = n.get('wait_until', 0)
        if type(minutes) is not int or not 0 <= minutes <= 1440:
            raise InvalidTree('预计时间应为 0–1440 分钟')
        if type(waiting) not in (float, int) or not math.isfinite(waiting) or waiting < 0:
            raise InvalidTree('等待时间格式错误')
        if type(n.get('collapsed', False)) is not bool:
            raise InvalidTree('折叠状态格式错误')
        for child in n['children']:
            visit(child, depth + 1)

    for root in roots:
        visit(root, 0)
    if seen != set(nodes):
        raise InvalidTree('存在未连接到分类的任务')
    return data


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
        dirfd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Forest:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'version': 1, 'roots': [], 'nodes': {}}
        self.undo_stack = []
        self.redo_stack = []
        self.recovery = ''
        if self.path.exists():
            try:
                self.data = validate(json.loads(self.path.read_text()))
            except (ValueError, TypeError, RecursionError) as error:
                backup = self.path.with_suffix('.json.bak')
                if not backup.exists():
                    raise InvalidTree(f'任务文件损坏，请先保留原文件并从导出恢复：{self.path}') from error
                self.data = validate(json.loads(backup.read_text()))
                damaged = self.path.with_name(f'tasks-damaged-{time.time_ns()}.json')
                atomic_write(damaged, self.path.read_bytes())
                atomic_write(self.path, self.encode(self.data))
                self.recovery = f'已从备份恢复，损坏文件保存在 {damaged}'

    @property
    def nodes(self):
        return self.data['nodes']

    @staticmethod
    def encode(data):
        return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()

    def persist(self, candidate):
        validate(candidate)
        if self.path.exists():
            atomic_write(self.path.with_suffix('.json.bak'), self.encode(self.data))
        atomic_write(self.path, self.encode(candidate))

    def change(self, action):
        candidate = copy.deepcopy(self.data)
        result = action(candidate)
        self.persist(candidate)
        self.undo_stack.append(self.data)
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()
        self.data = candidate
        return result

    def undo(self):
        if self.undo_stack:
            self.persist(self.undo_stack[-1])
            self.redo_stack.append(self.data)
            self.data = self.undo_stack.pop()

    def redo(self):
        if self.redo_stack:
            self.persist(self.redo_stack[-1])
            self.undo_stack.append(self.data)
            self.data = self.redo_stack.pop()

    def parent(self, key, data=None):
        for parent, node in (data or self.data)['nodes'].items():
            if key in node['children']:
                return parent
        return None

    def category(self, key):
        while self.parent(key) is not None:
            key = self.parent(key)
        return key

    def descendants(self, key, data=None):
        nodes = (data or self.data)['nodes']
        result, pending = [], list(nodes[key]['children'])
        while pending:
            item = pending.pop(0)
            result.append(item)
            pending.extend(nodes[item]['children'])
        return result

    def add(self, title, target=None, mode='child', minutes=0, wait_until=0):
        title = title.strip()
        if not title:
            raise InvalidTree('请填写任务名称')
        key = uuid.uuid4().hex

        def action(data):
            nodes = data['nodes']
            node = dict(title=title, kind='task' if target else 'category', children=[],
                        minutes=minutes, wait_until=wait_until, collapsed=False)
            if target is None:
                data['roots'].append(key)
            elif mode == 'child':
                nodes[target]['children'].append(key)
                nodes[target]['collapsed'] = False
            elif mode == 'after':
                if nodes[target]['kind'] == 'category':
                    raise InvalidTree('分类不能插入后置步骤')
                node['children'] = nodes[target]['children']
                nodes[target]['children'] = [key]
            elif mode in ('before', 'sibling'):
                parent = self.parent(target, data)
                if parent is None:
                    raise InvalidTree('请在任务节点上插入步骤')
                siblings = nodes[parent]['children']
                index = siblings.index(target)
                if mode == 'before':
                    siblings[index] = key
                    node['children'] = [target]
                else:
                    siblings.insert(index + 1, key)
            else:
                raise InvalidTree('不支持的位置')
            nodes[key] = node
            return key
        return self.change(action)

    def edit(self, key, **values):
        allowed = {'title', 'minutes', 'wait_until', 'collapsed'}
        if set(values) - allowed:
            raise InvalidTree('不支持的字段')
        return self.change(lambda data: data['nodes'][key].update(values))

    def complete(self, key):
        def action(data):
            node = data['nodes'][key]
            parent = self.parent(key, data)
            if parent is None:
                raise InvalidTree('分类不能标记完成')
            siblings = data['nodes'][parent]['children']
            index = siblings.index(key)
            siblings[index:index + 1] = node['children']
            del data['nodes'][key]
        self.change(action)

    def delete_branch(self, key):
        def action(data):
            parent = self.parent(key, data)
            siblings = data['roots'] if parent is None else data['nodes'][parent]['children']
            siblings.remove(key)
            for item in [key] + self.descendants(key, data):
                del data['nodes'][item]
        self.change(action)

    def can_move(self, key, target, mode):
        return (key in self.nodes and target in self.nodes and
                self.nodes[key]['kind'] == 'task' and key != target and
                target not in self.descendants(key) and
                mode in ('child', 'before', 'after') and
                (mode == 'child' or self.parent(target) is not None))

    def move(self, key, target, mode='child'):
        if not self.can_move(key, target, mode):
            raise InvalidTree('不能移入自己的后续分支，或放置位置无效')

        def action(data):
            nodes = data['nodes']
            nodes[self.parent(key, data)]['children'].remove(key)
            if mode == 'child':
                nodes[target]['children'].append(key)
                nodes[target]['collapsed'] = False
            else:
                siblings = nodes[self.parent(target, data)]['children']
                siblings.insert(siblings.index(target) + (mode == 'after'), key)
        self.change(action)

    def ready(self, minutes=0, now=None):
        now = time.time() if now is None else now
        return [(root, key) for root in self.data['roots']
                for key in self.nodes[root]['children']
                if self.nodes[key].get('wait_until', 0) <= now
                and (not minutes or 0 < self.nodes[key].get('minutes', 0) <= minutes)]

    def import_file(self, path):
        candidate = validate(json.loads(Path(path).read_text()))
        self.change(lambda data: (data.clear(), data.update(copy.deepcopy(candidate))))

    def export_file(self, path):
        if Path(path).resolve() in (self.path.resolve(), self.path.with_suffix('.json.bak').resolve()):
            raise InvalidTree('请导出到任务存储目录以外的位置')
        atomic_write(Path(path), self.encode(self.data))

    def seed_example(self):
        def action(data):
            def node(key, title, kind='task', children=None, minutes=0, wait_until=0):
                data['nodes'][key] = dict(title=title, kind=kind, children=children or [],
                                         minutes=minutes, wait_until=wait_until, collapsed=False)
            data['roots'] = ['dev', 'learn', 'life']
            node('dev', '开发与实验', 'category', ['run', 'readlog'])
            node('run', '程序正在运行', children=['check'], wait_until=time.time() + 20 * 60)
            node('check', '检查结果，记录下一次改动', minutes=10)
            node('readlog', '整理上一次实验笔记', minutes=5)
            node('learn', '学习与积累', 'category', ['read'])
            node('read', '读一小节资料', children=['note'], minutes=15)
            node('note', '写下一个理解或疑问', minutes=5)
            node('life', '生活与杂事', 'category', ['water', 'desk'])
            node('water', '起身喝水，活动一下', minutes=3)
            node('desk', '整理桌面的一小块', minutes=5)
        self.change(action)
