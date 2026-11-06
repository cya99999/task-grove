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

    def test_scheduled_includes_deep_nodes_and_ignores_parent_progress(self):
        self.f.edit(self.b, start_at=200)
        self.f.edit(self.c, due_at=300)
        self.assertEqual(self.f.scheduled(now=100), [(self.r, self.b), (self.r, self.c)])
        self.assertEqual(self.f.scheduled('overdue', now=350), [(self.r, self.c)])
        self.f.complete(self.b)  # Skipping the parent is allowed.
        self.assertEqual(self.f.scheduled(now=350), [(self.r, self.c)])

    def test_inbox_always_exists_and_is_protected(self):
        inbox = self.f.inbox
        self.assertEqual(self.f.nodes[inbox]['title'], '零散任务')
        with self.assertRaises(InvalidTree):
            self.f.delete_branch(inbox)
        with self.assertRaises(InvalidTree):
            self.f.edit(inbox, title='改名')
        self.assertEqual(self.f.add('零散任务'), inbox)

    def test_old_data_gets_inbox_and_wait_is_migrated_without_losing_nodes(self):
        original = copy.deepcopy(self.f.data)
        inbox = self.f.inbox
        del original['nodes'][inbox]
        original['roots'].remove(inbox)
        original['nodes'][self.b]['wait_until'] = 600
        self.path.write_text(json.dumps(original))
        loaded = Forest(self.path)
        self.assertEqual(loaded.nodes[self.b]['start_at'], 600)
        self.assertNotIn('wait_until', loaded.nodes[self.b])
        self.assertEqual(set(loaded.nodes) - {loaded.inbox}, set(original['nodes']))
        self.assertEqual(json.loads(self.path.with_suffix('.json.bak').read_text()), original)

    def test_schedule_fields_validate_and_round_trip(self):
        with self.assertRaises(InvalidTree):
            self.f.edit(self.b, start_at=500, due_at=400)
        self.f.edit(self.b, start_at=400, due_at=500)
        self.assertEqual(Forest(self.path).nodes[self.b]['due_at'], 500)
        self.f.edit(self.b, start_at=0, due_at=0)
        self.assertEqual(self.f.scheduled(), [])

    def test_delete_branch_and_undo(self):
        self.f.delete_branch(self.a)
        self.assertEqual(set(self.f.nodes), {self.r, self.f.inbox})
        self.f.undo()
        self.assertEqual(set(self.f.nodes), {self.r, self.a, self.b, self.c, self.f.inbox})
        self.f.delete_branch(self.r)
        self.assertEqual(self.f.data['roots'], [self.f.inbox])

    def test_export_import_and_undo(self):
        export = Path(self.temp.name) / 'export.json'
        self.f.export_file(export)
        original = copy.deepcopy(self.f.data)
        self.f.add('临时类别')
        self.f.import_file(export)
        self.assertEqual(self.f.data, original)
        self.f.undo()
        self.assertEqual(len(self.f.data['roots']), 3)
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

    def test_parallel_lines_are_one_atomic_undoable_change(self):
        before = copy.deepcopy(self.f.data)
        keys = self.f.add_lines(self.a, ['准备数据', '检查输出', '记录结果'])
        self.assertEqual(self.f.nodes[self.a]['children'], [self.b, self.c] + keys)
        for key in keys:
            self.assertEqual(self.f.parent(key), self.a)
            self.assertEqual(self.f.nodes[key]['presentation'], 'line')
        after = copy.deepcopy(self.f.data)
        self.f.undo()
        self.assertEqual(self.f.data, before)
        self.f.redo()
        self.assertEqual(Forest(self.path).data, after)

    def test_invalid_line_batch_does_not_partially_add_tasks(self):
        before = self.path.read_bytes()
        for titles in ([], ['有效', 'x' * 201], ['有效', ' '], ['有效', None]):
            with self.assertRaises(InvalidTree):
                self.f.add_lines(self.a, titles)
            self.assertEqual(self.path.read_bytes(), before)

    def test_lines_survive_parent_completion_and_cross_category_move(self):
        keys = self.f.add_lines(self.a, ['子任务一', '子任务二'])
        self.f.complete(self.a)
        self.assertEqual(self.f.parent(keys[0]), self.r)
        other = self.f.add('其他类别')
        self.f.move(keys[0], other)
        self.assertEqual(self.f.parent(keys[0]), other)
        self.assertEqual(self.f.nodes[keys[0]]['presentation'], 'line')
        self.f.edit(keys[0], due_at=500, presentation='card')
        self.assertIn((other, keys[0]), self.f.scheduled())
        self.assertEqual(self.f.nodes[keys[0]]['presentation'], 'card')

    def test_category_cannot_become_a_line(self):
        with self.assertRaises(InvalidTree):
            self.f.edit(self.r, presentation='line')
        with self.assertRaises(InvalidTree):
            self.f.add('新类别', presentation='line')


if __name__ == '__main__':
    unittest.main()
