#!/usr/bin/env python3
"""CLI progress indicators and user experience improvements."""

import sys
import time
from typing import Iterator, Any, Optional, Callable
from datetime import datetime, timedelta
import threading


class ProgressBar:
    """Simple progress bar for terminal output."""

    def __init__(
        self,
        total: int,
        title: str = "Progress",
        bar_width: int = 40,
        show_percentage: bool = True,
        show_time: bool = True
    ):
        """
        Initialize progress bar.

        Args:
            total: Total items to process
            title: Progress bar title
            bar_width: Width of progress bar in characters
            show_percentage: Whether to show percentage
            show_time: Whether to show elapsed/estimated time
        """
        self.total = total
        self.title = title
        self.bar_width = bar_width
        self.show_percentage = show_percentage
        self.show_time = show_time
        self.current = 0
        self.start_time = time.time()
        self.lock = threading.Lock()

    def update(self, amount: int = 1) -> None:
        """
        Update progress bar.

        Args:
            amount: Number of items completed
        """
        with self.lock:
            self.current = min(self.current + amount, self.total)
            self._draw()

    def set(self, current: int) -> None:
        """
        Set progress to specific value.

        Args:
            current: Current progress
        """
        with self.lock:
            self.current = min(current, self.total)
            self._draw()

    def _draw(self) -> None:
        """Draw progress bar."""
        if self.total == 0:
            return

        percentage = self.current / self.total
        filled = int(self.bar_width * percentage)
        bar = "█" * filled + "░" * (self.bar_width - filled)

        # Build output string
        output = f"\r{self.title}: [{bar}]"

        if self.show_percentage:
            output += f" {percentage*100:6.1f}%"

        if self.show_time:
            elapsed = time.time() - self.start_time
            if self.current > 0:
                eta = (elapsed / self.current) * (self.total - self.current)
                output += f" ({self._format_time(elapsed)}<{self._format_time(eta)})"
            else:
                output += f" ({self._format_time(elapsed)})"

        # Pad to clear previous longer output
        output = output.ljust(80)

        # Print without newline
        sys.stderr.write(output)
        sys.stderr.flush()

        # Print newline when complete
        if self.current == self.total:
            sys.stderr.write("\n")
            sys.stderr.flush()

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format time duration."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # Print final state
        if self.current != self.total:
            sys.stderr.write("\n")
            sys.stderr.flush()


class Spinner:
    """Animated spinner for long-running operations."""

    SPINNERS = {
        "dots": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        "line": ["-", "\\", "|", "/"],
        "arrow": ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
        "box": ["◰", "◳", "◲", "◱"],
        "circle": ["◐", "◓", "◑", "◒"],
    }

    def __init__(
        self,
        title: str = "Loading",
        spinner_type: str = "dots",
        delay: float = 0.1
    ):
        """
        Initialize spinner.

        Args:
            title: Spinner title
            spinner_type: Type of spinner animation
            delay: Delay between frames in seconds
        """
        self.title = title
        self.spinner_type = spinner_type
        self.delay = delay
        self.running = False
        self.thread = None
        self.frames = self.SPINNERS.get(spinner_type, self.SPINNERS["dots"])

    def start(self) -> None:
        """Start spinner."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop spinner."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()

    def _spin(self) -> None:
        """Spin animation loop."""
        frame_index = 0

        while self.running:
            frame = self.frames[frame_index % len(self.frames)]
            output = f"\r{frame} {self.title}"
            sys.stderr.write(output)
            sys.stderr.flush()

            frame_index += 1
            time.sleep(self.delay)

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


class Table:
    """Simple ASCII table for displaying data."""

    def __init__(self, headers: list, title: str = ""):
        """
        Initialize table.

        Args:
            headers: Column headers
            title: Table title
        """
        self.headers = headers
        self.title = title
        self.rows = []

    def add_row(self, *values):
        """
        Add row to table.

        Args:
            *values: Row values (must match header count)
        """
        if len(values) != len(self.headers):
            raise ValueError(f"Expected {len(self.headers)} values, got {len(values)}")

        self.rows.append(values)

    def print(self) -> None:
        """Print table to stdout."""
        if not self.rows:
            return

        # Calculate column widths
        widths = [len(str(h)) for h in self.headers]
        for row in self.rows:
            for i, value in enumerate(row):
                widths[i] = max(widths[i], len(str(value)))

        # Print title
        if self.title:
            total_width = sum(widths) + len(self.headers) * 3 + 1
            print(f"\n{self.title.center(total_width)}")

        # Print header
        separator = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        print(separator)

        header_row = "|"
        for i, h in enumerate(self.headers):
            header_row += f" {str(h).ljust(widths[i])} |"
        print(header_row)

        print(separator)

        # Print rows
        for row in self.rows:
            row_str = "|"
            for i, value in enumerate(row):
                row_str += f" {str(value).ljust(widths[i])} |"
            print(row_str)

        print(separator)


class ColorOutput:
    """ANSI color output for terminal."""

    # Color codes
    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
    }

    @staticmethod
    def colorize(text: str, color: str) -> str:
        """
        Colorize text.

        Args:
            text: Text to colorize
            color: Color name

        Returns:
            Colored text
        """
        if color not in ColorOutput.COLORS:
            return text

        color_code = ColorOutput.COLORS[color]
        reset_code = ColorOutput.COLORS["reset"]
        return f"{color_code}{text}{reset_code}"

    @staticmethod
    def success(text: str) -> str:
        """Format success message."""
        return ColorOutput.colorize(f"✓ {text}", "green")

    @staticmethod
    def error(text: str) -> str:
        """Format error message."""
        return ColorOutput.colorize(f"✗ {text}", "red")

    @staticmethod
    def warning(text: str) -> str:
        """Format warning message."""
        return ColorOutput.colorize(f"⚠ {text}", "yellow")

    @staticmethod
    def info(text: str) -> str:
        """Format info message."""
        return ColorOutput.colorize(f"ℹ {text}", "blue")


def progress_iterator(
    iterable: Iterator[Any],
    total: int,
    title: str = "Processing"
) -> Iterator[Any]:
    """
    Wrap iterator with progress bar.

    Args:
        iterable: Iterator to wrap
        total: Total items
        title: Progress bar title

    Yields:
        Items from iterator
    """
    with ProgressBar(total, title) as pbar:
        for item in iterable:
            yield item
            pbar.update(1)


if __name__ == "__main__":
    # Test progress bar
    print("=== Progress Bar Test ===")
    with ProgressBar(100, "Downloading") as pbar:
        for i in range(100):
            time.sleep(0.01)
            pbar.update()

    # Test spinner
    print("\n=== Spinner Test ===")
    with Spinner("Processing", spinner_type="dots") as spinner:
        time.sleep(3)

    # Test table
    print("\n=== Table Test ===")
    table = Table(["Memo ID", "Title", "Tags", "Status"], "Memo List")
    table.add_row("001", "Python Tips", "python,dev", "active")
    table.add_row("002", "Database Design", "database,sql", "archived")
    table.add_row("003", "CLI Tools", "python,cli", "active")
    table.print()

    # Test colors
    print("\n=== Color Output Test ===")
    print(ColorOutput.success("Operation completed successfully"))
    print(ColorOutput.error("An error occurred"))
    print(ColorOutput.warning("This is a warning"))
    print(ColorOutput.info("This is information"))

    # Test progress iterator
    print("\n=== Progress Iterator Test ===")
    items = list(range(50))
    for item in progress_iterator(items, len(items), "Processing items"):
        time.sleep(0.02)
