"""A tiny, safe markdown-to-HTML renderer for reference content (spec §5.4).

The curated reference & action-guide content (``content/<param>.md``) is
authored in markdown and is **user-editable**, so it must be treated as
untrusted when rendered into a page. Rather than pull in a markdown runtime
dependency (CLAUDE.md "minimal deps"; spec §7.5), this module renders the small
subset the content actually uses — paragraphs, bullet lists, **bold** and
_italic_ — after HTML-escaping every character. The escape happens *before* any
markup is added, so no author-supplied HTML can reach the browser (no injection).

The renderer is intentionally Flask-free and pure (``str`` in, ``str`` out) so
it can be unit-tested in isolation; the app wires it up as a Jinja filter named
``markdown`` in :func:`fishy.create_app`.
"""

from __future__ import annotations

import html
import re

# Inline spans. Applied to already-escaped text, so ``*`` / ``_`` survive the
# escape untouched and only our own tags are introduced.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)")

# A bullet-list line: ``- item`` or ``* item`` (any leading indent).
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")


def _inline(text: str) -> str:
    """Escape ``text`` then apply the supported inline spans (bold, italic)."""
    escaped = html.escape(text, quote=False)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    return escaped


def render_markdown(text: str | None) -> str:
    """Render a small, safe subset of markdown to an HTML fragment string.

    Supported: blank-line-separated paragraphs, ``-``/``*`` bullet lists (with
    wrapped/indented continuation lines), ``**bold**`` and ``_italic_`` spans.
    All input is HTML-escaped first, so the output is safe to mark as trusted.

    Anything unrecognised degrades gracefully to escaped paragraph text — a
    missing or partially-formatted section never raises.
    """
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush_para() -> None:
        if para:
            joined = " ".join(line.strip() for line in para if line.strip())
            if joined:
                blocks.append("<p>" + _inline(joined) + "</p>")
            para.clear()

    def flush_list() -> None:
        if items:
            lis = "".join("<li>" + _inline(item) + "</li>" for item in items)
            blocks.append("<ul>" + lis + "</ul>")
            items.clear()

    for line in lines:
        if not line.strip():
            flush_para()
            flush_list()
            continue

        match = _BULLET_RE.match(line)
        if match:
            flush_para()
            items.append(match.group(1).strip())
        elif items and (line.startswith(" ") or line.startswith("\t")):
            # Indented continuation of the current bullet (wrapped long line).
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            flush_list()
            para.append(line)

    flush_para()
    flush_list()
    return "".join(blocks)
