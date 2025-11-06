#!/usr/bin/env python3
"""Markdown rendering support for memo application."""

import re
from typing import List, Dict
from pathlib import Path


class SimpleMarkdownRenderer:
    """Simple Markdown renderer for terminal display."""

    def __init__(self, width: int = 80):
        self.width = width
        self.colors = {
            'reset': '\033[0m',
            'bold': '\033[1m',
            'italic': '\033[3m',
            'underline': '\033[4m',
            'red': '\033[31m',
            'green': '\033[32m',
            'yellow': '\033[33m',
            'blue': '\033[34m',
            'magenta': '\033[35m',
            'cyan': '\033[36m',
            'gray': '\033[90m'
        }

    def render(self, text: str, use_colors: bool = True) -> str:
        """Render markdown text for terminal display."""
        lines = text.split('\n')
        rendered_lines = []

        in_code_block = False
        list_stack = []

        for line in lines:
            stripped = line.strip()

            # Code blocks
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                if use_colors:
                    rendered_lines.append(f"{self.colors['gray']}{'─' * self.width}{self.colors['reset']}")
                else:
                    rendered_lines.append('─' * self.width)
                continue

            if in_code_block:
                if use_colors:
                    rendered_lines.append(f"{self.colors['gray']}{line}{self.colors['reset']}")
                else:
                    rendered_lines.append(line)
                continue

            # Headers
            if stripped.startswith('#'):
                level = len(stripped) - len(stripped.lstrip('#'))
                header_text = stripped[level:].strip()

                if level == 1:
                    if use_colors:
                        rendered_lines.append(f"{self.colors['bold']}{self.colors['blue']}{header_text}{self.colors['reset']}")
                        rendered_lines.append(f"{self.colors['blue']}{'=' * len(header_text)}{self.colors['reset']}")
                    else:
                        rendered_lines.append(header_text)
                        rendered_lines.append('=' * len(header_text))
                elif level == 2:
                    if use_colors:
                        rendered_lines.append(f"{self.colors['bold']}{self.colors['cyan']}{header_text}{self.colors['reset']}")
                        rendered_lines.append(f"{self.colors['cyan']}{'-' * len(header_text)}{self.colors['reset']}")
                    else:
                        rendered_lines.append(header_text)
                        rendered_lines.append('-' * len(header_text))
                else:
                    if use_colors:
                        rendered_lines.append(f"{self.colors['bold']}{header_text}{self.colors['reset']}")
                    else:
                        rendered_lines.append(header_text)
                continue

            # Lists
            list_match = re.match(r'^(\s*)([-*+]|\d+\.)\s+(.+)$', stripped)
            if list_match:
                indent, marker, content = list_match.groups()
                indent_level = len(indent) // 2

                if marker in ['-', '*', '+']:
                    bullet = '•'
                else:
                    bullet = marker

                prefix = '  ' * indent_level + bullet + ' '
                if use_colors:
                    rendered_lines.append(f"{prefix}{self._format_inline(content, use_colors)}")
                else:
                    rendered_lines.append(f"{prefix}{self._format_inline(content, use_colors)}")
                continue

            # Checkboxes
            checkbox_match = re.match(r'^(\s*)- \[([ x])\]\s+(.+)$', stripped)
            if checkbox_match:
                indent, checked, content = checkbox_match.groups()
                checkbox = '☑' if checked.lower() == 'x' else '☐'
                prefix = indent + checkbox + ' '

                if use_colors and checked.lower() == 'x':
                    rendered_lines.append(f"{prefix}{self.colors['gray']}{self._format_inline(content, use_colors)}{self.colors['reset']}")
                else:
                    rendered_lines.append(f"{prefix}{self._format_inline(content, use_colors)}")
                continue

            # Blockquotes
            if stripped.startswith('>'):
                quote_text = stripped[1:].strip()
                if use_colors:
                    rendered_lines.append(f"{self.colors['gray']}│ {self._format_inline(quote_text, use_colors)}{self.colors['reset']}")
                else:
                    rendered_lines.append(f"│ {self._format_inline(quote_text, use_colors)}")
                continue

            # Horizontal rules
            if re.match(r'^[-*_]{3,}$', stripped):
                if use_colors:
                    rendered_lines.append(f"{self.colors['gray']}{'─' * self.width}{self.colors['reset']}")
                else:
                    rendered_lines.append('─' * self.width)
                continue

            # Regular paragraphs
            if stripped:
                rendered_lines.append(self._format_inline(line, use_colors))
            else:
                rendered_lines.append('')

        return '\n'.join(rendered_lines)

    def _format_inline(self, text: str, use_colors: bool = True) -> str:
        """Format inline markdown elements."""
        if not use_colors:
            # Strip markdown formatting for plain text
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Bold
            text = re.sub(r'\*(.*?)\*', r'\1', text)      # Italic
            text = re.sub(r'`(.*?)`', r'\1', text)        # Code
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links
            return text

        # Bold
        text = re.sub(r'\*\*(.*?)\*\*',
                     f"{self.colors['bold']}\\1{self.colors['reset']}", text)

        # Italic
        text = re.sub(r'\*(.*?)\*',
                     f"{self.colors['italic']}\\1{self.colors['reset']}", text)

        # Inline code
        text = re.sub(r'`(.*?)`',
                     f"{self.colors['yellow']}\\1{self.colors['reset']}", text)

        # Links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)',
                     f"{self.colors['blue']}{self.colors['underline']}\\1{self.colors['reset']}", text)

        # Highlight memo references [[ID]]
        text = re.sub(r'\[\[([a-fA-F0-9]{8,})\]\]',
                     f"{self.colors['magenta']}[[\\1]]{self.colors['reset']}", text)

        # Hashtags
        text = re.sub(r'#(\w+)',
                     f"{self.colors['cyan']}#\\1{self.colors['reset']}", text)

        return text

    def render_table(self, rows: List[List[str]], headers: List[str] = None, use_colors: bool = True) -> str:
        """Render a simple table."""
        if not rows:
            return ""

        all_rows = [headers] + rows if headers else rows

        # Calculate column widths
        col_widths = []
        for col_idx in range(max(len(row) for row in all_rows)):
            max_width = max(len(str(row[col_idx])) if col_idx < len(row) else 0
                          for row in all_rows)
            col_widths.append(min(max_width, self.width // len(all_rows[0])))

        lines = []

        # Header
        if headers:
            header_line = "│ " + " │ ".join(
                str(headers[i]).ljust(col_widths[i]) for i in range(len(headers))
            ) + " │"

            if use_colors:
                lines.append(f"{self.colors['bold']}{header_line}{self.colors['reset']}")
            else:
                lines.append(header_line)

            separator = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
            lines.append(separator)

        # Data rows
        for row in (rows if headers else all_rows):
            row_line = "│ " + " │ ".join(
                str(row[i] if i < len(row) else "").ljust(col_widths[i])
                for i in range(len(col_widths))
            ) + " │"
            lines.append(row_line)

        # Border
        border = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"
        if not headers:
            top_border = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
            lines.insert(0, top_border)
        lines.append(border)

        return '\n'.join(lines)


def render_memo_markdown(memo: Dict, width: int = 80, use_colors: bool = True) -> str:
    """Render a memo with markdown formatting."""
    renderer = SimpleMarkdownRenderer(width)

    # Render the main text
    rendered_text = renderer.render(memo['text'], use_colors)

    return rendered_text


def extract_markdown_metadata(text: str) -> Dict:
    """Extract metadata from markdown text (YAML frontmatter style)."""
    lines = text.split('\n')

    if len(lines) < 3 or lines[0].strip() != '---':
        return {}

    metadata = {}
    in_frontmatter = True

    for i, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            in_frontmatter = False
            break

        if ':' in line:
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip()

    return metadata


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()

            renderer = SimpleMarkdownRenderer()
            print(renderer.render(text))
        else:
            print(f"File not found: {file_path}")
    else:
        # Demo
        demo_text = """# Markdown Demo

This is a **bold** text and this is *italic*.

## Lists

- Item 1
- Item 2
  - Nested item
  - Another nested

## Tasks

- [x] Completed task
- [ ] Pending task

## Code

Here's some `inline code` and a block:

```python
def hello():
    print("Hello, World!")
```

## Quote

> This is a blockquote
> with multiple lines

## Links and References

Check out [[20250927]] for more info.
Also see this #tag for related content.

---

That's all!"""

        renderer = SimpleMarkdownRenderer()
        print(renderer.render(demo_text))