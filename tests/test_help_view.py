"""Tests for in-app documentation (help_view)."""

from __future__ import annotations

from bot.help_view import (
    DOC_PAGES,
    docs_root,
    markdown_to_html,
    render_help_page_html,
    resolve_doc_path,
    rewrite_internal_md_links,
)


def test_docs_root_exists() -> None:
    root = docs_root()
    assert root.is_dir()
    assert (root / "README.md").is_file()


def test_resolve_doc_path_known_slugs() -> None:
    assert resolve_doc_path("") is not None
    assert resolve_doc_path("settings") is not None
    assert resolve_doc_path("configuration-overview") is None
    assert resolve_doc_path("nope") is None


def test_all_doc_pages_exist() -> None:
    root = docs_root()
    for slug, fname in DOC_PAGES.items():
        p = root / fname
        assert p.is_file(), f"missing {fname} for slug {slug!r}"


def test_rewrite_internal_md_links() -> None:
    html = '<p><a href="main-dashboard.md#portfolio-summary">x</a></p>'
    out = rewrite_internal_md_links(html)
    assert 'href="/help/main-dashboard#portfolio-summary"' in out


def test_render_help_page_html_includes_nav() -> None:
    md = "# Title\n\nHello.\n"
    html = render_help_page_html(slug="", md_raw=md)
    assert "Title" in html
    assert '/help/settings"' in html or "/help/settings" in html


def test_markdown_to_html_has_fenced_code() -> None:
    md = "```\nBOT_MODE=live\n```\n"
    html = markdown_to_html(md)
    assert "<pre>" in html or "<code>" in html
