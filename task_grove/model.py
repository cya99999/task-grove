"""Ordered task forest, independent of Qt. All mutations are validated and atomic."""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid


INBOX_TITLE = '零散任务'


def normalize(data):
    """Upgrade optional fields without dropping any existing tasks."""
    if not any(data['nodes'][key]['title'] == INBOX_TITLE for key in data['roots']):
        key = '__inbox__' if '__inbox__' not in data['nodes'] else uuid.uuid4().hex
        data['nodes'][key] = dict(kind='category', title=INBOX_TITLE, children=[], minutes=0, collapsed=False)
        data['roots'].insert(0, key)
    for node in data['nodes'].values():
        if node.get('wait_until', 0) and not node.get('start_at', 0):
            node['start_at'] = node['wait_until']
        node.pop('wait_until', None)
        original_children = node['children']
        original_details = node.get('details', [])
        node['children'] = [key for key in original_children if data['nodes'][key].get('presentation') != 'line'] + [key for key in original_details if data['nodes'][key].get('presentation') != 'line']
        details = [key for key in original_details if data['nodes'][key].get('presentation') == 'line'] + [key for key in original_children if data['nodes'][key].get('presentation') == 'line']
        if details or 'details' in node:
            node['details'] = details
    if 'completed' in data:
        data['completed'] = recent_completed(data['completed'])
    return data


def recent_completed(records, now=None):
    now = time.time() if now is None else now
    cutoff = datetime.fromtimestamp(now).date() - timedelta(days=6)
    return sorted((r for r in records if datetime.fromtimestamp(r['completed_at']).date() >= cutoff), key=lambda r: r['completed_at'], reverse=True)


class InvalidTree(ValueError):
    pass


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise InvalidTree('不支持的数据格式（需要 version 1）')
    nodes, roots = data.get('nodes'), data.get('roots')
    if not isinstance(nodes, dict) or not isinstance(roots, list) or len(nodes) > 10000:
        raise InvalidTree('任务数据不完整或节点超过 10000 个')
    records = data.get('completed', [])
    if not isinstance(records, list) or len(records) > 10000:
        raise InvalidTree('已完成记录格式错误或超过 10000 条')
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get('id'), str)
                or not isinstance(record.get('title'), str) or not 1 <= len(record['title']) <= 200
                or not isinstance(record.get('category'), str) or len(record['category']) > 200
                or type(record.get('completed_at')) not in (int, float)
                or not math.isfinite(record['completed_at']) or not 0 <= record['completed_at'] <= 253402300799):
            raise InvalidTree('已完成记录格式错误')
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
        if n.get('presentation', 'card') not in ('card', 'line') or (depth == 0 and n.get('presentation', 'card') != 'card'):
            raise InvalidTree('分类使用树干卡片；任务可显示为卡片或细分支')
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
        for field in ('start_at', 'due_at'):
            stamp = n.get(field, 0)
            if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= stamp <= 253402300799:
                raise InvalidTree('开始或截止时间格式错误')
        if n.get('start_at', 0) and n.get('due_at', 0) and n['due_at'] < n['start_at']:
            raise InvalidTree('截止时间不能早于开始时间')
        if type(n.get('priority', False)) is not bool:
            raise InvalidTree('优先标记格式错误')
        planned = n.get('planned_for', '')
        if not isinstance(planned, str):
            raise InvalidTree('预计完成日期格式错误')
        if planned:
            try:
                if date.fromisoformat(planned).isoformat() != planned:
                    raise ValueError
            except ValueError as error:
                raise InvalidTree('预计完成日期应为 YYYY-MM-DD') from error
        if type(n.get('collapsed', False)) is not bool:
            raise InvalidTree('折叠状态格式错误')
        if not isinstance(n.get('details', []), list):
            raise InvalidTree('细节列表格式错误')
        for child in n['children'] + n.get('details', []):
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

        candidate = normalize(copy.deepcopy(self.data))
        if candidate != self.data or not self.path.exists():
            self.persist(candidate)
            self.data = candidate

    @property
    def nodes(self):
        return self.data['nodes']

    @property
    def inbox(self):
        return next(key for key in self.data['roots'] if self.nodes[key]['title'] == INBOX_TITLE)

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
        normalize(candidate)
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
            if key in node['children'] or key in node.get('details', []):
                return parent
        return None

    def relation(self, key, data=None):
        data = data or self.data
        parent = self.parent(key, data)
        return 'details' if parent is not None and key in data['nodes'][parent].get('details', []) else 'children'

    def category(self, key):
        while self.parent(key) is not None:
            key = self.parent(key)
        return key

    def descendants(self, key, data=None):
        nodes = (data or self.data)['nodes']
        result, pending = [], list(nodes[key]['children']) + list(nodes[key].get('details', []))
        while pending:
            item = pending.pop(0)
            result.append(item)
            pending.extend(nodes[item]['children'] + nodes[item].get('details', []))
        return result

    def add(self, title, target=None, mode='child', minutes=0, start_at=0, due_at=0, presentation='card', planned_for='', priority=False):
        title = title.strip()
        if not title:
            raise InvalidTree('请填写任务名称')
        if target is None and title == INBOX_TITLE:
            return self.inbox
        key = uuid.uuid4().hex

        def action(data):
            nodes = data['nodes']
            node = dict(title=title, kind='task' if target else 'category', children=[],
                        minutes=minutes, start_at=start_at, due_at=due_at, collapsed=False, presentation=presentation, planned_for=planned_for, priority=priority)
            if target is None:
                data['roots'].append(key)
            elif presentation == 'line':
                nodes[target].setdefault('details', []).append(key)
                nodes[target]['collapsed'] = False
            elif self.relation(target, data) == 'details' and mode in ('before', 'after', 'sibling'):
                owner = self.parent(target, data)
                siblings = nodes[owner]['details']
                siblings.insert(siblings.index(target) + (mode != 'before'), key)
                node['presentation'] = 'line'
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

    def add_lines(self, target, titles):
        """Append parallel lightweight tasks as one atomic, undoable operation."""
        if not isinstance(titles, list) or not titles or not all(isinstance(title, str) for title in titles):
            raise InvalidTree('请每行填写一个细分支任务')
        titles = [title.strip() for title in titles]
        if any(not title or len(title) > 200 for title in titles):
            raise InvalidTree('每个细分支名称应为 1–200 个字符')
        keys = [uuid.uuid4().hex for _ in titles]
        def action(data):
            parent = data['nodes'][target]
            for key, title in zip(keys, titles):
                data['nodes'][key] = dict(title=title, kind='task', children=[], minutes=0,
                                         start_at=0, due_at=0, collapsed=False, presentation='line')
            parent.setdefault('details', []).extend(keys)
            parent['collapsed'] = False
            return keys
        return self.change(action)

    def edit(self, key, **values):
        allowed = {'title', 'minutes', 'start_at', 'due_at', 'collapsed', 'presentation', 'planned_for', 'priority'}
        if key == self.inbox and values.get('title', INBOX_TITLE) != INBOX_TITLE:
            raise InvalidTree('零散任务是常驻分类，不能重命名')
        if set(values) - allowed:
            raise InvalidTree('不支持的字段')
        return self.change(lambda data: data['nodes'][key].update(values))

    def completed(self, now=None):
        return recent_completed(self.data.get('completed', []), now)

    def complete(self, key, record=True):
        def action(data):
            node = data['nodes'][key]
            parent = self.parent(key, data)
            if parent is None:
                raise InvalidTree('分类不能标记完成')
            if record:
                data.setdefault('completed', []).append(dict(id=uuid.uuid4().hex, title=node['title'], category=data['nodes'][self.category(key)]['title'], completed_at=time.time()))
            siblings = data['nodes'][parent][self.relation(key, data)]
            index = siblings.index(key)
            siblings[index:index + 1] = node['children']
            attached = []
            for detail in node.get('details', []):
                attached.extend([detail] + self.descendants(detail, data))
            for detail in attached:
                del data['nodes'][detail]
            del data['nodes'][key]
        self.change(action)

    def delete_branch(self, key):
        if key == self.inbox:
            raise InvalidTree('零散任务是常驻分类，可删除其中的任务，不能删除树干')
        def action(data):
            parent = self.parent(key, data)
            siblings = data['roots'] if parent is None else data['nodes'][parent][self.relation(key, data)]
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
            nodes[self.parent(key, data)][self.relation(key, data)].remove(key)
            if mode == 'child':
                relation = 'details' if nodes[key].get('presentation') == 'line' else 'children'
                nodes[target].setdefault(relation, []).append(key)
                nodes[target]['collapsed'] = False
            else:
                relation = self.relation(target, data)
                siblings = nodes[self.parent(target, data)][relation]
                siblings.insert(siblings.index(target) + (mode == 'after'), key)
                nodes[key]['presentation'] = 'line' if relation == 'details' else 'card'
        self.change(action)

    def scheduled(self, scope='all', now=None):
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now).date()
        result = []
        for key, node in self.nodes.items():
            if node['kind'] != 'task':
                continue
            stamps = [node[field] for field in ('start_at', 'due_at') if node.get(field, 0)]
            if not stamps:
                continue
            if scope == 'today' and not any(datetime.fromtimestamp(t).date() == today for t in stamps):
                continue
            if scope == 'overdue' and not (0 < node.get('due_at', 0) < now):
                continue
            result.append((self.category(key), key))
        return sorted(result, key=lambda pair: (not self.nodes[pair[1]].get('priority', False), min(self.nodes[pair[1]].get(field, 0) or float('inf') for field in ('start_at', 'due_at'))))

    def planned_today(self, now=None):
        """Incomplete plans and scheduled work carry forward without changing deadlines."""
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now).date()
        result = []
        for key, node in self.nodes.items():
            if node['kind'] != 'task':
                continue
            planned = node.get('planned_for', '')
            manual = bool(planned and date.fromisoformat(planned) <= today)
            timed = any(node.get(field) and datetime.fromtimestamp(node[field]).date() <= today for field in ('start_at', 'due_at'))
            if manual or timed:
                result.append((self.category(key), key))
        return sorted(result, key=lambda pair: not self.nodes[pair[1]].get('priority', False))

    def priority_later(self, now=None):
        today = {key for _, key in self.planned_today(now)}
        return [(self.category(key), key) for key, node in self.nodes.items()
                if node['kind'] == 'task' and node.get('priority', False) and key not in today]

    def today_source(self, key, now=None):
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now).date()
        node = self.nodes[key]
        if ((node.get('planned_for') and date.fromisoformat(node['planned_for']) < today)
                or any(node.get(field) and datetime.fromtimestamp(node[field]).date() < today for field in ('start_at', 'due_at'))):
            return '已顺延'
        if any(node.get(field) and datetime.fromtimestamp(node[field]).date() == today for field in ('start_at', 'due_at')):
            return '今日定时'
        return '今日预计'

    def import_file(self, path):
        candidate = validate(json.loads(Path(path).read_text()))
        self.change(lambda data: (data.clear(), data.update(copy.deepcopy(candidate))))

    def export_file(self, path):
        if Path(path).resolve() in (self.path.resolve(), self.path.with_suffix('.json.bak').resolve()):
            raise InvalidTree('请导出到任务存储目录以外的位置')
        atomic_write(Path(path), self.encode(self.data))

    def seed_example(self):
        def action(data):
            data['nodes'].clear()
            def node(key, title, kind='task', children=None, minutes=0, start_at=0, due_at=0):
                data['nodes'][key] = dict(title=title, kind=kind, children=children or [],
                                         minutes=minutes, start_at=start_at, due_at=due_at, collapsed=False)
            data['roots'] = ['dev', 'learn', 'life']
            node('dev', '开发与实验', 'category', ['run', 'readlog'])
            node('run', '程序正在运行', children=['check'], start_at=time.time() + 20 * 60)
            node('check', '检查结果，记录下一次改动', minutes=10)
            node('readlog', '整理上一次实验笔记', minutes=5)
            node('learn', '学习与积累', 'category', ['read'])
            node('read', '读一小节资料', children=['note'], minutes=15)
            node('note', '写下一个理解或疑问', minutes=5)
            node('life', '生活与杂事', 'category', ['water', 'desk'])
            node('water', '起身喝水，活动一下', minutes=3)
            node('desk', '整理桌面的一小块', minutes=5)
        self.change(action)
