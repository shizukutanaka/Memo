#!/usr/bin/env python3
"""Reminder system for memos."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import logging


class Reminder:
    """Represents a memo reminder."""

    def __init__(self, memo_id: str, remind_at: datetime, message: str, recurring: Optional[str] = None):
        self.memo_id = memo_id
        self.remind_at = remind_at
        self.message = message
        self.recurring = recurring  # daily, weekly, monthly
        self.created_at = datetime.now()
        self.snoozed_until = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'memo_id': self.memo_id,
            'remind_at': self.remind_at.isoformat(),
            'message': self.message,
            'recurring': self.recurring,
            'created_at': self.created_at.isoformat(),
            'snoozed_until': self.snoozed_until.isoformat() if self.snoozed_until else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Reminder':
        """Create from dictionary."""
        reminder = cls(
            memo_id=data['memo_id'],
            remind_at=datetime.fromisoformat(data['remind_at']),
            message=data['message'],
            recurring=data.get('recurring'),
        )
        reminder.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('snoozed_until'):
            reminder.snoozed_until = datetime.fromisoformat(data['snoozed_until'])
        return reminder

    def is_due(self) -> bool:
        """Check if reminder is due."""
        now = datetime.now()
        if self.snoozed_until and now < self.snoozed_until:
            return False
        return now >= self.remind_at

    def snooze(self, minutes: int = 10):
        """Snooze reminder for specified minutes."""
        self.snoozed_until = datetime.now() + timedelta(minutes=minutes)

    def get_next_occurrence(self) -> Optional[datetime]:
        """Get next occurrence for recurring reminders."""
        if not self.recurring:
            return None

        if self.recurring == 'daily':
            return self.remind_at + timedelta(days=1)
        elif self.recurring == 'weekly':
            return self.remind_at + timedelta(weeks=1)
        elif self.recurring == 'monthly':
            return self.remind_at + timedelta(days=30)

        return None


class ReminderManager:
    """Manage memo reminders."""

    def __init__(self, data_dir: Path, logger: Optional[logging.Logger] = None):
        self.data_dir = data_dir
        self.reminders_file = data_dir / "reminders.json"
        self.logger = logger or logging.getLogger(__name__)
        self.reminders: List[Reminder] = []
        self._load_reminders()

    def _load_reminders(self):
        """Load reminders from file."""
        if not self.reminders_file.exists():
            return

        try:
            with open(self.reminders_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.reminders = [Reminder.from_dict(r) for r in data]
        except Exception as e:
            self.logger.error(f"Failed to load reminders: {e}")

    def _save_reminders(self):
        """Save reminders to file."""
        try:
            with open(self.reminders_file, 'w', encoding='utf-8') as f:
                data = [r.to_dict() for r in self.reminders]
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save reminders: {e}")

    def add_reminder(self, memo_id: str, remind_at: datetime, message: str, recurring: Optional[str] = None):
        """Add a new reminder."""
        reminder = Reminder(memo_id, remind_at, message, recurring)
        self.reminders.append(reminder)
        self._save_reminders()
        return reminder

    def remove_reminder(self, memo_id: str):
        """Remove all reminders for a memo."""
        self.reminders = [r for r in self.reminders if r.memo_id != memo_id]
        self._save_reminders()

    def get_due_reminders(self) -> List[Reminder]:
        """Get all due reminders."""
        due = [r for r in self.reminders if r.is_due()]
        return due

    def get_upcoming_reminders(self, hours: int = 24) -> List[Reminder]:
        """Get reminders due within specified hours."""
        now = datetime.now()
        cutoff = now + timedelta(hours=hours)
        upcoming = [
            r for r in self.reminders
            if now <= r.remind_at <= cutoff
        ]
        return sorted(upcoming, key=lambda r: r.remind_at)

    def snooze_reminder(self, memo_id: str, minutes: int = 10):
        """Snooze a reminder."""
        for reminder in self.reminders:
            if reminder.memo_id == memo_id:
                reminder.snooze(minutes)
        self._save_reminders()

    def process_recurring(self):
        """Process recurring reminders."""
        for reminder in self.reminders[:]:
            if reminder.is_due() and reminder.recurring:
                next_time = reminder.get_next_occurrence()
                if next_time:
                    # Create new reminder for next occurrence
                    self.add_reminder(
                        reminder.memo_id,
                        next_time,
                        reminder.message,
                        reminder.recurring
                    )
                # Remove the old one
                self.reminders.remove(reminder)
        self._save_reminders()

    def show_due_reminders(self) -> str:
        """Format due reminders for display."""
        due = self.get_due_reminders()
        if not due:
            return "No due reminders"

        lines = ["🔔 Due Reminders:"]
        for reminder in due:
            lines.append(f"  [{reminder.memo_id}] {reminder.message}")
            lines.append(f"    Due: {reminder.remind_at.strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(lines)

    def show_upcoming_reminders(self, hours: int = 24) -> str:
        """Format upcoming reminders for display."""
        upcoming = self.get_upcoming_reminders(hours)
        if not upcoming:
            return f"No reminders in the next {hours} hours"

        lines = [f"📅 Upcoming Reminders (next {hours}h):"]
        for reminder in upcoming:
            lines.append(f"  [{reminder.memo_id}] {reminder.message}")
            lines.append(f"    At: {reminder.remind_at.strftime('%Y-%m-%d %H:%M')}")
            if reminder.recurring:
                lines.append(f"    Recurring: {reminder.recurring}")

        return "\n".join(lines)
