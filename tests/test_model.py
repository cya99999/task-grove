import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from task_grove.model import Forest, InvalidTree, validate


class ForestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tasks.json'
        self.f = Forest(self.path)
        self.r = self.f.add('开发')
        self.a = self.f.add('运行', self.r)
        self.b = self.f.add('检查', self.a)
        self.c = self.f.add('记录', self.a)

    def test_complete_promotes_all_children_in_order(self):
        last = self.f.add('其他并行任务', self.r)
        self.f.complete(self.a)
        self.assertEqual(self.f.nodes[self.r]['children'], [self.b, self.c, last])
        self.assertNotIn(self.a, self.f.nodes)
        self.assertEqual(Forest(self.path).data, self.f.data)

    def test_insert_before_and_after_preserves_dependencies(self):
        before = self.f.add('准备', self.a, 'before')
        after = self.f.add('收集结果', self.a, 'after')
        self.assertEqual(self.f.nodes[self.r]['children'], [before])
        self.assertEqual(self.f.nodes[before]['children'], [self.a])
        self.assertEqual(self.f.nodes[self.a]['children'], [after])
        self.assertEqual(self.f.nodes[after]['children'], [self.b, self.c])

    def test_sibling_is_parallel(self):
        other = self.f.add('并行', self.a, 'sibling')
        self.assertEqual(self.f.nodes[self.r]['children'], [self.a, other])
        self.assertEqual(self.f.nodes[self.a]['children'], [self.b, self.c])

    def test_cross_category_move_carries_subtree(self):
        root = self.f.add('生活')
        self.f.move(self.a, root)
        self.assertEqual(self.f.nodes[self.r]['children'], [])
        self.assertEqual(self.f.nodes[root]['children'], [self.a])
        self.assertEqual(self.f.category(self.b), root)
        self.assertEqual(self.f.nodes[self.a]['children'], [self.b, self.c])

    def test_reorder_same_parent_and_move_under_sibling(self):
        self.f.move(self.c, self.b, 'before')
        self.assertEqual(self.f.nodes[self.a]['children'], [self.c, self.b])
        self.f.move(self.c, self.b, 'after')
        self.assertEqual(self.f.nodes[self.a]['children'], [self.b, self.c])
        self.f.move(self.c, self.b)
        self.assertEqual(self.f.nodes[self.b]['children'], [self.c])

    def test_cycle_moves_rejected_without_changing_disk(self):
        previous = self.path.read_bytes()
        for key, target in [(self.a, self.b), (self.a, self.a), (self.r, self.a)]:
            with self.assertRaises(InvalidTree):
                self.f.move(key, target)
            self.assertEqual(self.path.read_bytes(), previous)

    def test_undo_redo_and_new_change_clears_redo(self):
        before = copy.deepcopy(self.f.data)
        self.f.complete(self.a)
        after = copy.deepcopy(self.f.data)
        self.f.undo()
        self.assertEqual(self.f.data, before)
        self.f.redo()
        self.assertEqual(self.f.data, after)
        self.f.undo()
        self.f.edit(self.a, title='新的名字')
        self.assertEqual(self.f.redo_stack, [])

    def test_ready_excludes_dependencies_waiting_and_unknown_duration(self):
        self.f.edit(self.a, minutes=5, wait_until=100)
        parallel = self.f.add('短任务', self.r, minutes=3)
        self.assertEqual(self.f.ready(5, now=50), [(self.r, parallel)])
        self.assertEqual(self.f.ready(5, now=101), [(self.r, self.a), (self.r, parallel)])
        self.f.edit(self.a, minutes=0)
        self.assertEqual(self.f.ready(5, now=101), [(self.r, parallel)])
        self.assertEqual(len(self.f.ready(now=101)), 2)

    def test_delete_branch_and_undo(self):
        self.f.delete_branch(self.a)
        self.assertEqual(set(self.f.nodes), {self.r})
        self.f.undo()
        self.assertEqual(set(self.f.nodes), {self.r, self.a, self.b, self.c})
        self.f.delete_branch(self.r)
        self.assertEqual(self.f.data['roots'], [])
        self.assertEqual(self.f.nodes, {})

    def test_export_import_and_undo(self):
        export = Path(self.temp.name) / 'export.json'
        self.f.export_file(export)
        original = copy.deepcopy(self.f.data)
        self.f.add('临时类别')
        self.f.import_file(export)
        self.assertEqual(self.f.data, original)
        self.f.undo()
        self.assertEqual(len(self.f.data['roots']), 2)
        with self.assertRaises(InvalidTree):
            self.f.export_file(self.path)

    def test_invalid_import_does_not_destroy_tasks(self):
        path = Path(self.temp.name) / 'invalid.json'
        invalid = copy.deepcopy(self.f.data)
        invalid['nodes'][self.b]['children'] = [self.a]
        path.write_text(json.dumps(invalid))
        previous = self.path.read_bytes()
        with self.assertRaises(InvalidTree):
            self.f.import_file(path)
        self.assertEqual(self.path.read_bytes(), previous)

    def test_recovery_preserves_corrupt_file(self):
        backup = json.loads(self.path.with_suffix('.json.bak').read_text())
        self.path.write_text('damaged')
        recovered = Forest(self.path)
        self.assertEqual(recovered.data, backup)
        self.assertTrue(recovered.recovery)
        self.assertEqual(list(Path(self.temp.name).glob('tasks-damaged-*.json'))[0].read_text(), 'damaged')

    def test_no_backup_corruption_refuses_to_start(self):
        self.path.with_suffix('.json.bak').unlink()
        self.path.write_text('damaged')
        with self.assertRaises(InvalidTree):
            Forest(self.path)
        self.assertEqual(self.path.read_text(), 'damaged')

    def test_write_failure_does_not_mutate_memory(self):
        previous = copy.deepcopy(self.f.data)
        with patch('task_grove.model.atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.f.complete(self.a)
        self.assertEqual(self.f.data, previous)
        self.assertEqual(Forest(self.path).data, previous)

    def test_validator_rejects_orphans_invalid_fields_and_duplicate_roots(self):
        for mutate in [lambda d: d['roots'].append(self.r),
                       lambda d: d['nodes'][self.a].update(wait_until=float('nan')),
                       lambda d: d['nodes'][self.a].update(minutes=-1),
                       lambda d: d['nodes'][self.r]['children'].clear(),
                       lambda d: d['nodes'][self.a].update(title=' '),
                       lambda d: d['nodes'][self.a].update(children=['missing'])]:
            data = copy.deepcopy(self.f.data)
            mutate(data)
            with self.assertRaises(InvalidTree):
                validate(data)


if __name__ == '__main__':
    unittest.main()
