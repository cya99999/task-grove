import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from task_grove.model import Forest, InvalidTree, validate


class ForestTests(unittest.TestCase):
    def test_priority_later_excludes_today_and_carryover(self):
        now = datetime(2026,11,7,12).timestamp()
        later = self.f.add('未来优先',self.r,priority=True,start_at=now+86400)
        unplanned = self.f.add('未定优先',self.r,priority=True)
        self.f.add('今日优先',self.r,priority=True,planned_for='2026-11-07')
        self.f.add('顺延优先',self.r,priority=True,planned_for='2026-11-06')
        self.f.add('今日定时优先',self.r,priority=True,due_at=now+3600)
        self.f.add('普通未来',self.r,start_at=now+86400)
        self.assertEqual({key for _,key in self.f.priority_later(now)},{later,unplanned})

    def test_completion_history_promotes_steps_and_undo_removes_record(self):
        child = self.f.add('下一步', self.a)
        with patch('task_grove.model.time.time', return_value=1700000000):
            self.f.complete(self.a)
            records = self.f.completed(now=1700000000)
        self.assertEqual(records[0]['title'], '运行')
        self.assertEqual(records[0]['category'], '开发')
        self.assertEqual(self.f.parent(child), self.r)
        self.f.undo()
        self.assertIn(self.a, self.f.nodes)
        self.assertEqual(self.f.completed(), [])
        self.f.complete(self.a, record=False)
        self.assertEqual(self.f.completed(), [])

    def test_completion_retention_is_seven_calendar_dates_and_prunes_on_save(self):
        now = datetime.now().replace(hour=12, minute=0, second=0).timestamp()
        day = datetime.fromtimestamp(now)
        def record(days):
            return dict(id=str(days),title='记录',category='开发',completed_at=(day-timedelta(days=days)).replace(hour=0).timestamp())
        self.f.data['completed'] = [record(6),record(7),record(0)]
        self.assertEqual([r['id'] for r in self.f.completed(now)], ['0','6'])
        with patch('task_grove.model.time.time',return_value=now):
            self.f.edit(self.a,title='更新')
        self.assertEqual([r['id'] for r in self.f.data['completed']], ['0','6'])
        self.assertEqual(Forest(self.path).data['completed'],self.f.data['completed'])
        broken = copy.deepcopy(self.f.data);broken['completed'][0]['completed_at']='invalid'
        with self.assertRaises(InvalidTree):validate(broken)

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
        self.assertEqual(self.f.nodes[self.a]['children'], [self.b, self.c])
        self.assertEqual(self.f.nodes[self.a]['details'], keys)
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

    def test_details_stay_with_owner_and_do_not_become_following_steps(self):
        keys = self.f.add_lines(self.a, ['当前步骤细节一', '当前步骤细节二'])
        other = self.f.add('其他类别')
        self.f.move(keys[0], other)
        self.assertEqual(self.f.nodes[other]['details'], [keys[0]])
        self.f.complete(self.a)
        self.assertEqual(self.f.nodes[self.r]['children'], [self.b, self.c])
        self.assertNotIn(keys[1], self.f.nodes)
        self.assertIn(keys[0], self.f.nodes)
        self.f.edit(keys[0], due_at=500, presentation='card')
        self.assertIn((other, keys[0]), self.f.scheduled())
        self.assertEqual(self.f.nodes[other]['children'], [keys[0]])
        self.assertEqual(self.f.nodes[other]['details'], [])

    def test_old_line_children_migrate_to_attached_details(self):
        old = copy.deepcopy(self.f.data)
        old['nodes'][self.b]['presentation'] = 'line'
        self.path.write_text(json.dumps(old))
        loaded = Forest(self.path)
        self.assertEqual(loaded.nodes[self.a]['children'], [self.c])
        self.assertEqual(loaded.nodes[self.a]['details'], [self.b])
        self.assertEqual(json.loads(self.path.with_suffix('.json.bak').read_text()), old)

    def test_detail_descendants_participate_in_cycle_protection_and_delete(self):
        detail = self.f.add_lines(self.a, ['细节'])[0]
        nested = self.f.add_lines(detail, ['更细的说明'])[0]
        self.assertFalse(self.f.can_move(self.a, nested, 'child'))
        self.f.delete_branch(self.a)
        self.assertNotIn(detail, self.f.nodes)
        self.assertNotIn(nested, self.f.nodes)

    def test_category_cannot_become_a_line(self):
        with self.assertRaises(InvalidTree):
            self.f.edit(self.r, presentation='line')
        with self.assertRaises(InvalidTree):
            self.f.add('新类别', presentation='line')

    def test_today_contains_manual_plans_and_deep_scheduled_tasks(self):
        now = datetime(2026, 11, 7, 9).timestamp()
        self.f.edit(self.b, planned_for='2026-11-07')
        detail = self.f.add_lines(self.a, ['今天的细节'])[0]
        self.f.edit(detail, due_at=now + 3600)
        tomorrow = self.f.add('明天的任务', self.r, start_at=now + 86400)
        today = {key for _, key in self.f.planned_today(now)}
        self.assertEqual(today, {self.b, detail})
        self.assertNotIn(tomorrow, today)

    def test_priority_is_marked_and_first_in_both_lists(self):
        now = datetime(2026, 11, 7, 9).timestamp()
        self.f.edit(self.b, planned_for='2026-11-07', due_at=now + 100)
        self.f.edit(self.c, planned_for='2026-11-07', due_at=now + 200, priority=True)
        self.assertEqual(self.f.planned_today(now)[0][1], self.c)
        self.assertEqual(self.f.scheduled(now=now)[0][1], self.c)

    def test_unfinished_manual_plan_rolls_over_without_changing_deadlines(self):
        now = datetime(2026, 11, 7, 23, 59).timestamp()
        self.f.edit(self.b, planned_for='2026-11-07', due_at=now + 86400)
        before = self.path.read_bytes()
        for stamp in (now, now + 120, now + 5 * 86400):
            self.assertIn((self.r, self.b), self.f.planned_today(stamp))
        self.assertEqual(self.f.today_source(self.b, now + 120), '已顺延')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.f.nodes[self.b]['due_at'], now + 86400)

    def test_unfinished_scheduled_work_is_automatically_carried_forward(self):
        now = datetime(2026, 11, 7, 9).timestamp()
        self.f.edit(self.b, start_at=now + 3600)
        self.assertIn((self.r, self.b), self.f.planned_today(now))
        self.assertIn((self.r, self.b), self.f.planned_today(now + 86400))
        self.assertEqual(self.f.today_source(self.b, now + 86400), '已顺延')
        self.f.complete(self.b)
        self.assertNotIn((self.r, self.b), self.f.planned_today(now + 2 * 86400))

    def test_priority_alone_does_not_add_an_unplanned_task_to_today(self):
        now = datetime(2026, 11, 7, 9).timestamp()
        self.f.edit(self.b, priority=True)
        self.assertNotIn((self.r, self.b), self.f.planned_today(now))

    def test_invalid_plan_flags_do_not_change_saved_data(self):
        before = self.path.read_bytes()
        for values in ({'priority':'yes'}, {'priority':1}, {'planned_for':False}, {'planned_for':'2026-02-30'}, {'planned_for':'tomorrow'}):
            with self.assertRaises(InvalidTree):
                self.f.edit(self.b, **values)
            self.assertEqual(self.path.read_bytes(), before)

    def test_plan_flags_survive_export_import_undo_and_reload(self):
        self.f.edit(self.b, planned_for='2026-11-07', priority=True)
        exported = Path(self.temp.name) / 'plan-export.json'
        self.f.export_file(exported)
        self.f.edit(self.b, planned_for='', priority=False)
        self.f.import_file(exported)
        loaded = Forest(self.path)
        self.assertTrue(loaded.nodes[self.b]['priority'])
        self.assertEqual(loaded.nodes[self.b]['planned_for'], '2026-11-07')
        self.f.undo()
        self.assertFalse(self.f.nodes[self.b]['priority'])

    def test_old_nodes_default_to_unplanned_without_migration(self):
        before = self.path.read_bytes()
        self.assertEqual(self.f.planned_today(datetime(2026,11,7,9).timestamp()), [])
        self.assertEqual(Forest(self.path).data, self.f.data)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
