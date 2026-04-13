"""Serve Markdown documentation from the repo ``docs/`` folder as HTML."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

# Repo root: bot/ -> parent, project root -> parent.parent
_DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"

# Slug -> filename (must stay under docs/; no path traversal)
DOC_PAGES: dict[str, str] = {
    "": "README.md",
    "configuration-overview": "configuration-overview.md",
    "runtime-settings": "runtime-settings.md",
    "dashboard-ui": "dashboard-ui.md",
    "trading-and-safety": "trading-and-safety.md",
    "strategy-parameters": "strategy-parameters.md",
    "risk-controls": "risk-controls.md",
    "admin-and-auth": "admin-and-auth.md",
    "deployment": "deployment.md",
    "troubleshooting": "troubleshooting.md",
}


def docs_root() -> Path:
    return _DOCS_ROOT


def resolve_doc_path(slug: str) -> Path | None:
    slug = (slug or "").strip().lower().replace("/", "")
    if slug not in DOC_PAGES:
        return None
    path = (_DOCS_ROOT / DOC_PAGES[slug]).resolve()
    try:
        path.relative_to(_DOCS_ROOT.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def markdown_to_html(md_text: str) -> str:
    """Convert Markdown to HTML (requires ``markdown`` package)."""
    import markdown
    from markdown.extensions.attr_list import AttrListExtension
    from markdown.extensions.toc import TocExtension

    return markdown.markdown(
        md_text,
        extensions=[
            "extra",
            "sane_lists",
            AttrListExtension(),
            TocExtension(permalink=False, toc_depth="2-4"),
        ],
    )


def rewrite_internal_md_links(html: str) -> str:
    """Turn links like ``configuration-overview.md#foo`` into ``/help/...`` paths."""
    file_to_slug = {fn: sl for sl, fn in DOC_PAGES.items()}

    def repl(match: re.Match[str]) -> str:
        fname = match.group(1)
        frag = match.group(2) or ""
        if fname not in file_to_slug:
            return match.group(0)
        sl = file_to_slug[fname]
        base = "/help" if sl == "" else f"/help/{sl}"
        return f'href="{base}{frag}"'

    return re.sub(r'href="([A-Za-z0-9_.-]+\.md)(#[a-zA-Z0-9_-]+)?"', repl, html)


def render_help_page_html(*, slug: str, md_raw: str) -> str:
    title = escape(_title_from_markdown(md_raw, "Documentation"))
    body = rewrite_internal_md_links(markdown_to_html(md_raw))
    nav_order = [
        "",
        "dashboard-ui",
        "configuration-overview",
        "runtime-settings",
        "trading-and-safety",
        "strategy-parameters",
        "risk-controls",
        "admin-and-auth",
        "deployment",
        "troubleshooting",
    ]
    nav_items = []
    for nav_slug in nav_order:
        if nav_slug not in DOC_PAGES:
            continue
        fname = DOC_PAGES[nav_slug]
        label = "Overview" if nav_slug == "" else fname.replace(".md", "").replace("-", " ").title()
        href = "/help" if nav_slug == "" else f"/help/{nav_slug}"
        active = " active" if slug == nav_slug else ""
        nav_items.append(f'<a class="help-nav-link{active}" href="{escape(href)}">{escape(label)}</a>')
    nav_html = "".join(nav_items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — NEH docs</title>
<style>
:root {{
  --bg: #0f172a;
  --card: #1e293b;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --border: #334155;
  --accent: #38bdf8;
  --code-bg: #0c1222;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
}}
.help-top {{
  background: var(--card);
  border-bottom: 1px solid var(--border);
  padding: 0.75rem 1.25rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1rem;
  position: sticky;
  top: 0;
  z-index: 10;
}}
.help-top a.home {{
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
  margin-right: 0.5rem;
}}
.help-nav {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
  align-items: center;
}}
.help-nav-link {{
  color: var(--muted);
  text-decoration: none;
  font-size: 0.8rem;
}}
.help-nav-link:hover {{ color: var(--text); }}
.help-nav-link.active {{ color: var(--accent); font-weight: 600; }}
.wrap {{
  max-width: 52rem;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}}
.help-body :where(h1, h2, h3, h4) {{ line-height: 1.25; margin: 1.75rem 0 0.75rem; }}
.help-body h1 {{ font-size: 1.75rem; margin-top: 0; }}
.help-body h2 {{ font-size: 1.2rem; border-bottom: 1px solid var(--border); padding-bottom: 0.35rem; }}
.help-body p {{ margin: 0.75rem 0; }}
.help-body ul, .help-body ol {{ margin: 0.5rem 0 0.75rem 1.25rem; }}
.help-body li {{ margin: 0.25rem 0; }}
.help-body a {{ color: var(--accent); }}
.help-body code {{
  background: var(--code-bg);
  padding: 0.12rem 0.35rem;
  border-radius: 4px;
  font-size: 0.88em;
}}
.help-body pre {{
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  overflow: auto;
  font-size: 0.85rem;
}}
.help-body pre code {{ background: none; padding: 0; }}
.help-body table {{
  border-collapse: collapse;
  width: 100%;
  margin: 1rem 0;
  font-size: 0.9rem;
}}
.help-body th, .help-body td {{
  border: 1px solid var(--border);
  padding: 0.5rem 0.65rem;
  text-align: left;
}}
.help-body th {{ background: var(--card); color: var(--muted); }}
.help-body blockquote {{
  margin: 1rem 0;
  padding-left: 1rem;
  border-left: 3px solid var(--accent);
  color: var(--muted);
}}
</style>
</head>
<body>
<header class="help-top">
  <a class="home" href="/">← Dashboard</a>
  <nav class="help-nav" aria-label="Documentation sections">{nav_html}</nav>
</header>
<div class="wrap help-body">
{body}
</div>
</body>
</html>"""
