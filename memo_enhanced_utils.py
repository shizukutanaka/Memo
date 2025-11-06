#!/usr/bin/env python3
"""Enhanced utility functions for memo system."""

import sys
import time
from typing import Iterator, Optional, Callable
from datetime import datetime


class ProgressIndicator:
    """Simple progress indicator for long operations."""

    def __init__(self, total: Optional[int] = None, desc: str = "Processing", show_percent: bool = True):
        self.total = total
        self.desc = desc
        self.show_percent = show_percent
        self.current = 0
        self.start_time = time.time()
        self.last_update = 0

    def update(self, n: int = 1) -> None:
        """Update progress by n items."""
        self.current += n
        now = time.time()
        if now - self.last_update < 0.1:
            return
        self.last_update = now
        self._display()

    def _display(self) -> None:
        """Display current progress."""
        elapsed = time.time() - self.start_time
        if self.total and self.show_percent:
            percent = (self.current / self.total) * 100
            bar_length = 30
            filled = int(bar_length * self.current / self.total)
            bar = "█" * filled + "░" * (bar_length - filled)
            if self.current > 0:
                rate = self.current / elapsed
                remaining = (self.total - self.current) / rate if rate > 0 else 0
                eta = f"ETA: {remaining:.0f}s"
            else:
                eta = "ETA: --"
            sys.stdout.write(f"\r{self.desc}: [{bar}] {percent:.1f}% ({self.current}/{self.total}) {eta}")
        else:
            sys.stdout.write(f"\r{self.desc}: {self.current} items ({elapsed:.1f}s)")
        sys.stdout.flush()

    def finish(self) -> None:
        """Mark progress as complete."""
        elapsed = time.time() - self.start_time
        if self.total:
            sys.stdout.write(f"\r{self.desc}: [{'█' * 30}] 100% ({self.total}/{self.total}) Done in {elapsed:.1f}s\n")
        else:
            sys.stdout.write(f"\r{self.desc}: {self.current} items completed in {elapsed:.1f}s\n")
        sys.stdout.flush()


class ConfigValidator:
    """Validate configuration settings."""

    @staticmethod
    def validate_config(config_dict: dict) -> tuple:
        """Validate configuration dictionary."""
        errors = []
        
        if 'display' in config_dict:
            display = config_dict['display']
            if 'max_text_preview' in display:
                val = display['max_text_preview']
                if not isinstance(val, int) or val < 10 or val > 10000:
                    errors.append("display.max_text_preview must be between 10 and 10000")
        
        if 'limits' in config_dict:
            limits = config_dict['limits']
            if 'max_memo_bytes' in limits:
                val = limits['max_memo_bytes']
                if not isinstance(val, int) or val < 1024 or val > 10_000_000:
                    errors.append("limits.max_memo_bytes must be between 1024 and 10000000")
        
        is_valid = len(errors) == 0
        return is_valid, errors


def confirm_destructive_operation(operation: str, details: str = "") -> bool:
    """Confirm destructive operation with user."""
    print(f"⚠️  WARNING: You are about to {operation}")
    if details:
        print(f"   {details}")
    print("   This operation cannot be undone.")
    try:
        response = input("   Type 'yes' to confirm: ").strip().lower()
        return response == 'yes'
    except (KeyboardInterrupt, EOFError):
        print("\n   Operation cancelled")
        return False
