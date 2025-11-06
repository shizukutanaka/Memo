#!/usr/bin/env python3
"""Core memo storage and management functionality."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
import logging

from config import Config


class MemoCore:
    """Core memo data structure and basic operations."""

    def __init__(self, memo_id: str = None, text: str = "", tags: List[str] = None,
                 category: str = "default", status: str = "active", links: List[str] = None,
                 reminder: str = None, created: str = None, edited: str = None):
        self.id = memo_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        self.text = text.strip()
        self.tags = tags or []
        self.category = category
        self.status = status
        self.links = links or []
        self.reminder = reminder
        self.created = created or datetime.now(timezone.utc).isoformat()
        self.edited = edited or self.created

    def to_dict(self) -> Dict[str, Any]:
        """Convert memo to dictionary."""
        return {
            "id": self.id,
            "text": self.text,
            "tags": self.tags,
            "category": self.category,
            "status": self.status,
            "links": self.links,
            "reminder": self.reminder,
            "created": self.created,
            "edited": self.edited,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoCore':
        """Create memo from dictionary."""
        return cls(
            memo_id=data.get("id"),
            text=data.get("text", ""),
            tags=data.get("tags", []),
            category=data.get("category", "default"),
            status=data.get("status", "active"),
            links=data.get("links", []),
            reminder=data.get("reminder"),
            created=data.get("created"),
            edited=data.get("edited"),
        )

    def update(self, text: str = None, tags: List[str] = None, category: str = None,
               status: str = None, links: List[str] = None, reminder: str = None) -> None:
        """Update memo fields."""
        if text is not None:
            self.text = text.strip()
        if tags is not None:
            self.tags = tags
        if category is not None:
            self.category = category
        if status is not None:
            self.status = status
        if links is not None:
            self.links = links
        if reminder is not None:
            self.reminder = reminder
        self.edited = datetime.now(timezone.utc).isoformat()

    def is_due(self, before: Optional[datetime] = None) -> bool:
        """Check if memo has due reminder."""
        if not self.reminder:
            return False

        try:
            reminder_dt = datetime.fromisoformat(self.reminder)
            before = before or datetime.now(timezone.utc)
            return reminder_dt <= before
        except (TypeError, ValueError):
            return False


class MemoValidator:
    """Validate memo data and operations."""

    VALID_STATUSES = {"active", "completed", "archived"}
    MAX_TEXT_LENGTH = 100000
    MAX_TAGS = 50
    MAX_CATEGORY_LENGTH = 100
    MAX_TAG_LENGTH = 50

    @staticmethod
    def validate_text(text: str) -> tuple[bool, str]:
        """Validate memo text."""
        if not text or not text.strip():
            return False, "Text cannot be empty"

        if len(text) > MemoValidator.MAX_TEXT_LENGTH:
            return False, f"Text too long (max {MemoValidator.MAX_TEXT_LENGTH} characters)"

        return True, ""

    @staticmethod
    def validate_tags(tags: List[str]) -> tuple[bool, str]:
        """Validate memo tags."""
        if len(tags) > MemoValidator.MAX_TAGS:
            return False, f"Too many tags (max {MemoValidator.MAX_TAGS})"

        for tag in tags:
            if not tag or len(tag) > MemoValidator.MAX_TAG_LENGTH:
                return False, f"Invalid tag length: {tag}"
            if not tag.replace('-', '').replace('_', '').isalnum():
                return False, f"Invalid tag characters: {tag}"

        return True, ""

    @staticmethod
    def validate_category(category: str) -> tuple[bool, str]:
        """Validate memo category."""
        if len(category) > MemoValidator.MAX_CATEGORY_LENGTH:
            return False, f"Category too long (max {MemoValidator.MAX_CATEGORY_LENGTH} characters)"

        if not category.replace('-', '').replace('_', '').replace(' ', '').isalnum():
            return False, f"Invalid category characters: {category}"

        return True, ""

    @staticmethod
    def validate_status(status: str) -> tuple[bool, str]:
        """Validate memo status."""
        if status not in MemoValidator.VALID_STATUSES:
            return False, f"Invalid status: {status}"

        return True, ""

    @staticmethod
    def validate_memo(memo: MemoCore) -> tuple[bool, List[str]]:
        """Validate complete memo object."""
        errors = []

        valid, error = MemoValidator.validate_text(memo.text)
        if not valid:
            errors.append(f"Text: {error}")

        valid, error = MemoValidator.validate_tags(memo.tags)
        if not valid:
            errors.append(f"Tags: {error}")

        valid, error = MemoValidator.validate_category(memo.category)
        if not valid:
            errors.append(f"Category: {error}")

        valid, error = MemoValidator.validate_status(memo.status)
        if not valid:
            errors.append(f"Status: {error}")

        return len(errors) == 0, errors


class MemoStorage:
    """Base class for memo storage implementations."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or (Path.home() / ".memo")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = Config()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def add_memo(self, memo: MemoCore) -> bool:
        """Add a memo to storage."""
        raise NotImplementedError

    def get_memo(self, memo_id: str) -> Optional[MemoCore]:
        """Get a memo by ID."""
        raise NotImplementedError

    def update_memo(self, memo: MemoCore) -> bool:
        """Update a memo in storage."""
        raise NotImplementedError

    def delete_memo(self, memo_id: str) -> bool:
        """Delete a memo from storage."""
        raise NotImplementedError

    def list_memos(self, limit: int = 50, **filters) -> List[MemoCore]:
        """List memos with optional filters."""
        raise NotImplementedError

    def search_memos(self, query: str, **options) -> List[MemoCore]:
        """Search memos."""
        raise NotImplementedError

    def get_categories(self) -> List[str]:
        """Get all categories."""
        raise NotImplementedError

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        raise NotImplementedError


class MemoCollection:
    """Collection of memos with advanced operations."""

    def __init__(self, storage: MemoStorage):
        self.storage = storage
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def add_memo_from_dict(self, data: Dict[str, Any]) -> Optional[MemoCore]:
        """Add memo from dictionary data."""
        try:
            memo = MemoCore.from_dict(data)

            # Validate memo
            is_valid, errors = MemoValidator.validate_memo(memo)
            if not is_valid:
                self.logger.error(f"Invalid memo data: {errors}")
                return None

            if self.storage.add_memo(memo):
                return memo
            return None

        except Exception as e:
            self.logger.error(f"Failed to add memo from dict: {e}")
            return None

    def get_memo_by_id(self, memo_id: str) -> Optional[MemoCore]:
        """Get memo by ID."""
        return self.storage.get_memo(memo_id)

    def update_memo_from_dict(self, memo_id: str, updates: Dict[str, Any]) -> bool:
        """Update memo with dictionary data."""
        memo = self.storage.get_memo(memo_id)
        if not memo:
            return False

        # Apply updates
        memo.update(**updates)

        # Validate updated memo
        is_valid, errors = MemoValidator.validate_memo(memo)
        if not is_valid:
            self.logger.error(f"Invalid memo update: {errors}")
            return False

        return self.storage.update_memo(memo)

    def delete_memo_by_id(self, memo_id: str) -> bool:
        """Delete memo by ID."""
        return self.storage.delete_memo(memo_id)

    def list_memos_paginated(self, page: int = 1, per_page: int = 20, **filters) -> Dict[str, Any]:
        """List memos with pagination."""
        all_memos = self.storage.list_memos(limit=0, **filters)

        start = (page - 1) * per_page
        end = start + per_page

        return {
            'memos': all_memos[start:end],
            'total': len(all_memos),
            'page': page,
            'per_page': per_page,
            'total_pages': (len(all_memos) + per_page - 1) // per_page
        }

    def search_memos_advanced(self, query: str, **options) -> List[MemoCore]:
        """Advanced search with multiple options."""
        return self.storage.search_memos(query, **options)

    def get_memos_by_category(self, category: str) -> List[MemoCore]:
        """Get all memos in a category."""
        return self.storage.list_memos(limit=0, category=category)

    def get_memos_by_status(self, status: str) -> List[MemoCore]:
        """Get all memos with a specific status."""
        return self.storage.list_memos(limit=0, status=status)

    def get_memos_by_tag(self, tag: str) -> List[MemoCore]:
        """Get all memos with a specific tag."""
        return self.storage.list_memos(limit=0, tags=[tag])

    def get_due_reminders(self, before: Optional[datetime] = None) -> List[MemoCore]:
        """Get memos with due reminders."""
        all_memos = self.storage.list_memos(limit=0)
        before = before or datetime.now(timezone.utc)

        due_memos = []
        for memo in all_memos:
            if memo.is_due(before):
                due_memos.append(memo)

        return sorted(due_memos, key=lambda m: m.reminder or "")

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get comprehensive storage statistics."""
        stats = self.storage.get_stats()

        # Add additional computed stats
        all_memos = self.storage.list_memos(limit=0)
        categories = {}
        statuses = {}
        tags = {}

        for memo in all_memos:
            # Category stats
            categories[memo.category] = categories.get(memo.category, 0) + 1

            # Status stats
            statuses[memo.status] = statuses.get(memo.status, 0) + 1

            # Tag stats
            for tag in memo.tags:
                tags[tag] = tags.get(tag, 0) + 1

        stats.update({
            'categories': categories,
            'statuses': statuses,
            'tags': tags,
            'total_categories': len(categories),
            'total_tags': len(tags),
        })

        return stats


class MemoTemplate:
    """Handle memo templates."""

    def __init__(self, storage: MemoStorage):
        self.storage = storage
        self.templates_file = storage.data_dir / "templates.json"
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def get_templates(self) -> Dict[str, Dict[str, Any]]:
        """Get all templates."""
        if not self.templates_file.exists():
            return self._get_default_templates()

        try:
            with open(self.templates_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self.logger.warning(f"Failed to load templates: {e}")
            return self._get_default_templates()

    def save_templates(self, templates: Dict[str, Dict[str, Any]]) -> bool:
        """Save templates to file."""
        try:
            with open(self.templates_file, 'w', encoding='utf-8') as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            self.logger.error(f"Failed to save templates: {e}")
            return False

    def create_from_template(self, template_key: str, variables: Dict[str, str]) -> Optional[MemoCore]:
        """Create memo from template."""
        templates = self.get_templates()

        if template_key not in templates:
            self.logger.error(f"Template not found: {template_key}")
            return None

        template = templates[template_key]
        try:
            text = template["template"].format(**variables)
            tags = template.get("tags", [])
            category = template.get("category", "default")

            memo = MemoCore(text=text, tags=tags, category=category)

            if self.storage.add_memo(memo):
                return memo
            return None

        except KeyError as e:
            self.logger.error(f"Missing template variable: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to create memo from template: {e}")
            return None

    def _get_default_templates(self) -> Dict[str, Dict[str, Any]]:
        """Get default templates."""
        return {
            "meeting": {
                "name": "Meeting Notes",
                "template": "# Meeting: {title}\n\n**Date:** {date}\n**Attendees:** {attendees}\n\n## Agenda\n- \n\n## Notes\n\n\n## Action Items\n- [ ] \n\n## Next Steps\n",
                "category": "meetings",
                "tags": ["meeting"]
            },
            "task": {
                "name": "Task",
                "template": "# Task: {title}\n\n**Priority:** {priority}\n**Due:** {due_date}\n\n## Description\n{description}\n\n## Sub-tasks\n- [ ] \n\n## Notes\n",
                "category": "tasks",
                "tags": ["task", "todo"]
            },
            "idea": {
                "name": "Idea",
                "template": "# Idea: {title}\n\n## Description\n{description}\n\n## Potential Impact\n\n\n## Next Actions\n- [ ] Research further\n- [ ] Create prototype\n",
                "category": "ideas",
                "tags": ["idea", "brainstorm"]
            }
        }
