"""`gflow docs` against the **real** pages this repository ships (#861).

Separate from `test_cli_docs.py` on purpose. Those tests use a four-page fixture and
answer "does the code do what it says". These answer "does the feature solve the problem
it was filed for", and that question is only decidable against the actual corpus — 126
pages, 133 lines mentioning `duration`, and one of them being the rule that a run cost a
session. A fixture can be made to pass by choosing its contents.

Scenarios 8 and 11 from `SCENARIO.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gflow_cli import docs_catalog

_REPO_DOCS = Path(__file__).resolve().parents[2] / "docs"

pytestmark = pytest.mark.skipif(
    not _REPO_DOCS.is_dir(), reason="runs against the repository's own docs/ tree"
)


def test_every_shipped_page_is_a_topic_with_no_manifest_to_maintain() -> None:
    """Scenario 11. The directory listing IS the topic list, at build time and read time.

    If this ever fails because someone added a page, the right fix is not to update a
    list — it is that a list appeared somewhere and should be deleted.
    """
    on_disk = {p.name for p in _REPO_DOCS.glob("*.md")}
    catalogued = {t.file_name for t in docs_catalog.topics()}
    assert catalogued == on_disk
    assert len(on_disk) > 100, len(on_disk)  # the corpus this feature exists for


def test_every_topic_reports_a_path_that_exists() -> None:
    """The position printed next to a hit has to be openable.

    The first version built it from the slug, so `MCP.md` was reported as `docs/mcp.md` —
    a path that does not exist on a case-sensitive filesystem, handed to a reader as the
    answer.
    """
    for topic in docs_catalog.topics():
        assert (_REPO_DOCS.parent / topic.repo_path).is_file(), topic.repo_path


def test_the_query_that_filed_this_issue_finds_the_rule_it_missed() -> None:
    """Scenario 8 — the feature's acceptance test.

    #861 was filed after `video r2v --duration 10` against a host that offers r2v at 8 s
    only. The rule was already written down, inside a ~4 000-character bullet in `MCP.md`,
    and was never found. This is the query a reader would type, and it has to land.
    """
    matches = docs_catalog.search("r2v duration")
    assert matches, "the rule is unreachable — the feature does not do its job"
    assert matches[0].position.startswith("docs/MCP.md:"), [m.position for m in matches[:5]]
    # And the line must arrive readable. The raw line is over 4 000 characters; handing
    # that to a terminal is "go read the file" with extra steps.
    assert len(matches[0].text) < 250, len(matches[0].text)
    assert "duration" in matches[0].text.lower() or "r2v" in matches[0].text.lower()


def test_a_bare_common_word_is_answered_honestly_rather_than_silently_truncated() -> None:
    """The other half of scenario 8, and the limit this feature does not pretend past.

    `--search duration` alone has 133 hits and no ranking tried here could put the rule
    first (see `_score`'s docstring for the two that were built and measured). What the
    command owes the reader is the count and a way to narrow, not a confident wrong first
    result.
    """
    shown, held_back = docs_catalog.truncate_hits(docs_catalog.search("duration"))
    assert len(shown) <= 20
    assert held_back > 0, "a vague query must say how much it is not showing"


def test_the_curated_index_shortcuts_are_parsed_from_the_real_index() -> None:
    """Scenario 9's precondition. If `INDEX.md`'s format drifts this returns nothing and
    search still works — but ranking silently loses its best signal, so it is asserted."""
    rows = docs_catalog.shortcuts()
    assert len(rows) > 30, len(rows)
    assert all(question and line_no > 0 for line_no, question, _ in rows)
