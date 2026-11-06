"""Wall-clock reminders with persistent delivery marks and sleep catch-up."""
from datetime import datetime
import json
from pathlib import Path
import time

from .model import atomic_write


def schedule_text(node):
    parts = []
    for field, label in (('start_at', '开始'), ('due_at', '截止')):
        if node.get(field, 0):
            parts.append(label + ' ' + datetime.fromtimestamp(node[field]).strftime('%m-%d %H:%M'))
    return ' · '.join(parts)


class Reminders:
    def __init__(self, path, boot_id=None):
        self.path = Path(path)
        self.state = {'delivered': [], 'summary': ''}
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text())
                if (isinstance(state, dict) and isinstance(state.get('delivered'), list)
                        and all(isinstance(key, str) for key in state['delivered'])
                        and isinstance(state.get('summary'), str)):
                    self.state = state
            except (ValueError, OSError):
                pass  # Task data lives separately; a broken cache can only repeat a reminder.
        self.last_saved = json.dumps(self.state, ensure_ascii=False, sort_keys=True)
        self.delivered = set(self.state['delivered'])
        self.boot_id = boot_id
        if self.boot_id is None:
            try:
                self.boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            except OSError:
                self.boot_id = 'session'

    def poll(self, forest, send, now=None):
        """Send first, then persist. Missed thresholds collapse into the closest reminder."""
        now = time.time() if now is None else now
        summary = self.boot_id + ':' + datetime.fromtimestamp(now).strftime('%Y-%m-%d')
        if self.state['summary'] != summary:
            today = forest.scheduled('today', now)
            if today:
                lines = [forest.nodes[key]['title'] + '  ' + schedule_text(forest.nodes[key]) for _, key in today]
                send(f'今日还剩 {len(today)} 项定时任务', '\n'.join(lines))
            self.state['summary'] = summary
        valid = set()
        for _, key in forest.scheduled():
            node = forest.nodes[key]
            for field, label in (('start_at', '开始'), ('due_at', '截止')):
                stamp = node.get(field, 0)
                if not stamp:
                    continue
                tokens = {lead: f'{key}:{field}:{stamp}:{lead}' for lead in (3600, 600, 0)}
                valid.update(tokens.values())
                eligible = [lead for lead in tokens if now >= stamp - lead and tokens[lead] not in self.delivered]
                if eligible:
                    lead = min(eligible)
                    remaining = stamp - now
                    if remaining <= 0:
                        detail = f'已到{label}时间' if remaining > -60 else f'已过{label}时间，请查看'
                    else:
                        detail = f'距离{label}还剩 {max(1, int((remaining + 59) // 60))} 分钟'
                    send(node['title'], detail + '\n' + schedule_text(node))
                    # If the machine slept across several thresholds, do not replay old alerts.
                    self.delivered.update(tokens[item] for item in eligible)
        self.delivered.intersection_update(valid)
        self.state['delivered'] = sorted(self.delivered)
        encoded = json.dumps(self.state, ensure_ascii=False, sort_keys=True)
        if encoded != self.last_saved:
            atomic_write(self.path, (encoded + '\n').encode())
            self.last_saved = encoded
