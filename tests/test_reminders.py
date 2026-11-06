from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_grove.model import Forest
from task_grove.reminders import Reminders


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.forest = Forest(self.folder / 'tasks.json')
        self.now = datetime(2026, 11, 7, 9, 0).timestamp()
        self.key = self.forest.add('实验', self.forest.inbox, start_at=self.now + 7200, due_at=self.now + 14400)
        self.messages = []
        self.reminders = Reminders(self.folder / 'reminders.json', boot_id='boot-a')

    def poll(self, now, reminders=None):
        (reminders or self.reminders).poll(self.forest, lambda title, body: self.messages.append((title, body)), now)

    def alerts(self):
        return [message for message in self.messages if message[0] == '实验']

    def test_both_start_and_due_remind_at_hour_ten_minutes_and_time(self):
        self.poll(self.now)
        self.assertEqual(len(self.messages), 1)  # Morning summary.
        for field in ('start_at', 'due_at'):
            stamp = self.forest.nodes[self.key][field]
            for lead, expected in [(3600, '60 分钟'), (600, '10 分钟'), (0, '已到')]:
                count = len(self.alerts())
                self.poll(stamp - lead - 1)
                self.assertEqual(len(self.alerts()), count)
                self.poll(stamp - lead)
                self.assertEqual(len(self.alerts()), count + 1)
                self.assertIn(expected, self.alerts()[-1][1])
                self.poll(stamp - lead)
                self.assertEqual(len(self.alerts()), count + 1)
        self.assertEqual(len(self.alerts()), 6)

    def test_restart_does_not_repeat_delivered_threshold(self):
        self.poll(self.now + 3600)
        count = len(self.messages)
        restarted = Reminders(self.folder / 'reminders.json', boot_id='boot-a')
        self.poll(self.now + 3601, restarted)
        self.assertEqual(len(self.messages), count)
        self.poll(self.now + 6600, restarted)
        self.assertEqual(len(self.messages), count + 1)

    def test_new_boot_repeats_today_summary_without_replaying_alerts(self):
        self.poll(self.now + 3600)
        count = len(self.messages)
        restarted = Reminders(self.folder / 'reminders.json', boot_id='boot-b')
        self.poll(self.now + 3601, restarted)
        self.assertEqual(len(self.messages), count + 1)
        self.assertIn('今日还剩 1 项', self.messages[-1][0])

    def test_sleep_catchup_only_sends_closest_threshold(self):
        self.poll(self.now)
        self.poll(self.now + 7000)  # Wakes with about 3 minutes left.
        self.assertEqual(len(self.alerts()), 1)
        self.assertIn('4 分钟', self.alerts()[0][1])
        self.poll(self.now + 7200)
        self.assertEqual(len(self.alerts()), 2)

    def test_completed_and_cleared_tasks_do_not_notify(self):
        self.poll(self.now)
        self.forest.complete(self.key)
        self.poll(self.now + 14400)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(self.reminders.delivered, set())

    def test_editing_time_creates_new_reminder_schedule(self):
        self.poll(self.now + 3600)
        self.forest.edit(self.key, start_at=self.now + 8000)
        self.poll(self.now + 4400)
        self.assertEqual(len(self.alerts()), 2)

    def test_today_summary_includes_overdue_unfinished_but_excludes_other_dates(self):
        self.forest.edit(self.key, start_at=self.now - 3600, due_at=self.now - 10)
        self.forest.add('明天', self.forest.inbox, start_at=self.now + 86400)
        self.forest.add('未定时', self.forest.inbox)
        self.poll(self.now)
        summary = self.messages[0]
        self.assertIn('今日还剩 1 项', summary[0])
        self.assertIn('实验', summary[1])
        self.assertNotIn('明天', summary[1])

    def test_failed_cache_write_retries_without_repeating_notification(self):
        with patch('task_grove.reminders.atomic_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.poll(self.now + 3600)
        count = len(self.messages)
        self.poll(self.now + 3601)
        self.assertEqual(len(self.messages), count)
        self.assertTrue((self.folder / 'reminders.json').exists())

    def test_midnight_sends_next_days_summary(self):
        self.forest.add('明日任务', self.forest.inbox, start_at=self.now + 86400)
        self.poll(self.now)
        self.poll(self.now + 86400 - 9 * 3600)
        summaries = [m for m in self.messages if m[0].startswith('今日还剩')]
        self.assertEqual(len(summaries), 2)
        self.assertIn('明日任务', summaries[-1][1])


if __name__ == '__main__':
    unittest.main()
