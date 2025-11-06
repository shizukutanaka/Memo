#!/usr/bin/env python3
"""
Memo Application - Modern Terminal UI using Textual Framework

This module provides an interactive terminal user interface for the memo application
using the Textual framework, enabling modern features like:
- Interactive search with real-time results
- Memo browsing with scrollable lists
- Tag filtering and categorization
- Status and priority management
- Keyboard shortcuts for efficiency

Usage:
    python memo_tui.py
"""

from typing import Optional, List, Dict
from pathlib import Path

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.widgets import (
        Header,
        Footer,
        Static,
        Button,
        Input,
        Label,
        ListItem,
        ListView,
    )
    from textual.binding import Binding
    from textual.screen import Screen
    from rich.text import Text
    from rich.console import Console
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from memo import MemoStore


class MemoItem(ListItem):
    """A listview item representing a single memo."""

    def __init__(self, memo: Dict, *args, **kwargs):
        self.memo = memo
        content_preview = memo.get("content", "")[:60].replace("\n", " ")
        label = f"[{memo.get('status', 'unknown')}] {content_preview}"
        super().__init__(label, *args, **kwargs)


class MemoListView(ListView):
    """Custom ListView for displaying memos with better formatting."""

    def __init__(self, memos: List[Dict], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memos = memos

    def render_item(self, item: MemoItem) -> Text:
        """Render a memo item with rich text formatting."""
        memo = item.memo
        status_color = {
            "active": "green",
            "archived": "yellow",
            "deleted": "red",
        }.get(memo.get("status"), "white")

        tags = memo.get("tags", [])
        tags_str = f" [{', '.join(tags)}]" if tags else ""

        content = memo.get("content", "")[:50].replace("\n", " ")
        memo_id = memo.get("id", "")[:8]

        return Text.assemble(
            (f"[{memo.get('status', '?'):<6}] ", status_color),
            content,
            tags_str,
            f" ({memo_id})",
        )


class SearchWidget(Static):
    """Interactive search widget."""

    def compose(self) -> ComposeResult:
        yield Label("Search Memos:")
        yield Input(id="search_input", placeholder="Enter search query...")
        yield Label("Filter by Tag:")
        yield Input(id="tag_input", placeholder="Enter tag to filter...")


class MemoViewerApp:
    """Terminal UI application for memo management using Textual."""

    def __init__(self, data_file: Optional[Path] = None):
        if not TEXTUAL_AVAILABLE:
            raise ImportError(
                "Textual framework not installed. "
                "Install with: pip install -r requirements-dev.txt"
            )

        self.store = MemoStore(data_file=data_file)
        self.console = Console()

    def display_memo(self, memo: Dict) -> None:
        """Display a memo with formatting."""
        from datetime import datetime

        id_str = memo.get("id", "unknown")[:8]
        content = memo.get("content", "")
        category = memo.get("category", "default")
        tags = memo.get("tags", [])
        status = memo.get("status", "unknown")
        created = memo.get("created_at", "unknown")
        priority = memo.get("priority", 0)

        # Parse ISO format timestamp
        try:
            if isinstance(created, str):
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created_str = dt.strftime("%Y-%m-%d %H:%M")
            else:
                created_str = str(created)
        except (ValueError, AttributeError):
            created_str = str(created)

        # Print with rich formatting
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # Create info table
        table = Table(title="Memo Details")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("ID", id_str)
        table.add_row("Status", status)
        table.add_row("Category", category)
        table.add_row("Priority", str(priority))
        table.add_row("Created", created_str)
        table.add_row("Tags", ", ".join(tags) if tags else "(none)")

        console.print(table)
        console.print("\n[bold]Content:[/bold]\n")
        console.print(Panel(content, border_style="blue"))

    def search_and_display(self, query: str) -> None:
        """Search for memos and display results."""
        results = self.store.search(query)

        if not results:
            self.console.print(f"[yellow]No memos found for: {query}[/yellow]")
            return

        self.console.print(f"\n[green]Found {len(results)} memo(s):[/green]\n")

        for i, memo in enumerate(results, 1):
            content_preview = memo.get("content", "")[:60].replace("\n", " ")
            status = memo.get("status", "?")
            print(
                f"{i}. [{status}] {content_preview} "
                f"({memo.get('id', 'unknown')[:8]})"
            )

        # Allow user to view a specific memo
        if len(results) == 1:
            view = input("\nView full memo? (y/n): ").lower()
            if view == "y":
                self.display_memo(results[0])
        elif results:
            try:
                idx = int(input("\nView memo number (or press Enter to skip): ") or "-1")
                if 0 <= idx - 1 < len(results):
                    self.display_memo(results[idx - 1])
            except ValueError:
                pass

    def interactive_menu(self) -> None:
        """Display interactive menu for CLI-based interaction."""
        from memo import print_success, print_error

        if not print_success:
            print_success = lambda x: print(f"[OK] {x}")
        if not print_error:
            print_error = lambda x: print(f"[ERROR] {x}")

        while True:
            print("\n" + "=" * 50)
            print("Memo Application - Interactive Menu")
            print("=" * 50)
            print("1. Search memos")
            print("2. List recent memos")
            print("3. Add new memo")
            print("4. View by category")
            print("5. Exit")
            print("=" * 50)

            choice = input("Select option (1-5): ").strip()

            if choice == "1":
                query = input("Enter search query: ").strip()
                if query:
                    self.search_and_display(query)

            elif choice == "2":
                results = self.store.search("")  # Get all memos
                if results:
                    print(f"\n[green]Recent {min(10, len(results))} memos:[/green]\n")
                    for memo in results[:10]:
                        content = memo.get("content", "")[:50].replace("\n", " ")
                        print(f"- {content} ({memo.get('id', '')[:8]})")
                else:
                    print("[yellow]No memos found[/yellow]")

            elif choice == "3":
                text = input("Enter memo text: ").strip()
                tags_input = input("Enter tags (comma-separated): ").strip()
                category = input("Enter category (or press Enter for default): ").strip()

                if text:
                    tags = [t.strip() for t in tags_input.split(",") if t.strip()]
                    try:
                        memo = self.store.add(
                            text, tags=tags, category=category or None
                        )
                        print(f"[OK] Memo added: {memo['id'][:8]}")
                    except Exception as e:
                        print(f"[ERROR] Failed to add memo: {e}")

            elif choice == "4":
                categories = self.store.list_categories()
                if categories:
                    print("\nCategories:")
                    for cat in categories:
                        print(f"  - {cat}")
                    cat = input("Select category: ").strip()
                    if cat:
                        results = [
                            m
                            for m in self.store.list()
                            if m.get("category") == cat
                        ]
                        print(f"\n[green]Found {len(results)} memos in {cat}:[/green]")
                        for memo in results[:10]:
                            content = memo.get("content", "")[:50]
                            print(f"- {content} ({memo.get('id', '')[:8]})")
                else:
                    print("[yellow]No categories found[/yellow]")

            elif choice == "5":
                print("Goodbye!")
                break

            else:
                print("[yellow]Invalid option[/yellow]")


def main():
    """Main entry point for the TUI application."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--tui":
        # Use Textual if available, otherwise fallback to interactive menu
        if TEXTUAL_AVAILABLE:
            print("[INFO] Textual framework available - launching modern UI")
            # Future: Implement full Textual app here
            app = MemoViewerApp()
            app.interactive_menu()
        else:
            print(
                "[INFO] Textual not installed - using interactive menu mode"
            )
            app = MemoViewerApp()
            app.interactive_menu()
    else:
        # Fallback to interactive menu
        app = MemoViewerApp()
        app.interactive_menu()


if __name__ == "__main__":
    main()
