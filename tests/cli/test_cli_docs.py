"""`gflow docs` — resolution, refusal, encoding and `--json` (#861).

Covers `SCENARIO.md` scenarios 1, 2, 4, 6, 7, 10, 12, 16. The two that need the real
shipped pages live in `test_docs_catalog_real_docs.py`; the one that needs a built wheel
lives in `tests/integration/test_docs_ships_in_wheel.py`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from gflow_cli import docs_catalog
from gflow_cli.cli import main
from gflow_cli.errors import EXIT_CODE_MAP, ConfigurationError

_PAGES = {
    "USAGE.md": "# Usage\n\nCommand-by-command reference for every flag.\n",
    "USER_GUIDE.md": "# User Guide\n\nTask-oriented walkthroughs.\n",
    "CONFIGURATION.md": "# Configuration\n\nEnvironment variables and precedence.\n",
    "INDEX.md": (
        "# Documentation Index\n\n"
        "## Topic shortcuts\n\n"
        '**"Where do generated files land?"** → [CONFIGURATION](CONFIGURATION.md#paths)\n'
    ),
}


@pytest.fixture
def docs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A small documentation tree standing in for the shipped one."""
    directory = tmp_path / "docs"
    directory.mkdir()
    for name, body in _PAGES.items():
        (directory / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(docs_catalog, "_docs_dir", lambda: directory)
    return directory


def _run(*args: str) -> Any:
    return CliRunner().invoke(main, ["docs", *args], catch_exceptions=False)


# --- resolution -------------------------------------------------------------


@pytest.mark.parametrize("name", ["usage", "USAGE", "USAGE.md", "usage.md", "  usage  "])
def test_a_page_resolves_from_every_form_a_reader_types(docs_dir: Path, name: str) -> None:
    assert docs_catalog.resolve(name).file_name == "USAGE.md"


def test_an_unambiguous_prefix_resolves(docs_dir: Path) -> None:
    # Scenario 16: `gflow docs conf` is what a reader types; requiring the full name
    # makes the command feel broken for the most obvious input.
    assert docs_catalog.resolve("conf").file_name == "CONFIGURATION.md"


def test_an_ambiguous_prefix_is_refused_and_names_the_candidates(docs_dir: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        docs_catalog.resolve("us")
    detail = str(caught.value)
    assert "usage" in detail and "user-guide" in detail


def test_an_underscore_in_the_name_resolves_like_the_dash(docs_dir: Path) -> None:
    assert docs_catalog.resolve("user_guide").file_name == "USER_GUIDE.md"


# --- refusal ----------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../../etc/passwd",
        r"..\..\..\Windows\System32\config\SAM",
        "/etc/shadow",
        "C:\\Windows\\win.ini",
        "..",
        "../INDEX",
        "usage/../../secret",
    ],
)
def test_a_topic_name_is_never_used_to_build_a_path(docs_dir: Path, hostile: str) -> None:
    """Scenarios 1 and 2.

    The argument is a key looked up in the enumerated set of pages, so a traversal
    attempt is an ordinary unknown-topic refusal. Asserted per input anyway: this is the
    one property of this command whose breakage would be a file-read primitive, and a
    future refactor that starts joining paths must fail here.
    """
    with pytest.raises(ConfigurationError):
        docs_catalog.resolve(hostile)


def test_an_unknown_topic_exits_11_and_suggests(docs_dir: Path) -> None:
    # Scenario 6: a class already in EXIT_CODE_MAP — no new exception, no new exit code.
    assert EXIT_CODE_MAP[ConfigurationError] == 11
    # "guide" is nobody's prefix, but it IS inside `user-guide` — so the refusal has
    # something to offer. A refusal that only says no makes the reader run `docs` and
    # scan 126 rows, which is the state this command exists to end.
    result = _run("guide")
    assert result.exit_code == 11, result.output
    assert "user-guide" in result.output


def test_a_topic_and_a_search_together_are_refused(docs_dir: Path) -> None:
    result = _run("usage", "--search", "flag")
    assert result.exit_code == 11, result.output
    assert "not both" in result.output


# --- search -----------------------------------------------------------------


def test_a_search_with_no_matches_exits_zero(docs_dir: Path) -> None:
    # Scenario 7: an empty result is a true answer to a valid question, not a failure.
    result = _run("--search", "zzzznotinanypage")
    assert result.exit_code == 0, result.output


def test_a_curated_index_answer_outranks_a_body_hit(docs_dir: Path) -> None:
    # Scenario 9. "generated files land" is an INDEX shortcut; "Environment" is body text.
    matches = docs_catalog.search("generated files land")
    assert matches and matches[0].curated


def test_search_still_works_when_the_index_has_no_parseable_shortcuts(
    docs_dir: Path,
) -> None:
    # Scenario 10: the shortcut parser is additive. If INDEX.md's format changes, search
    # degrades to body text — it must not crash and must not silently return nothing.
    (docs_dir / "INDEX.md").write_text("# Index\n\nNo shortcuts here any more.\n", "utf-8")
    assert docs_catalog.shortcuts() == []
    matches = docs_catalog.search("precedence")
    assert matches and not matches[0].curated


def test_all_query_terms_must_appear_on_the_line(docs_dir: Path) -> None:
    assert docs_catalog.search("environment precedence")
    assert not docs_catalog.search("environment walkthroughs")


def test_a_long_line_is_windowed_around_the_match(docs_dir: Path) -> None:
    (docs_dir / "USAGE.md").write_text(
        "# Usage\n\n" + ("padding " * 400) + "NEEDLE" + (" padding" * 400) + "\n",
        encoding="utf-8",
    )
    text = docs_catalog.search("needle")[0].text
    assert "NEEDLE" in text
    assert len(text) < 250, len(text)  # not the 6 KB line


# --- rendering --------------------------------------------------------------


def test_a_page_full_of_non_ascii_prints_on_a_cp1252_console(
    docs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 4 — the #846 shape, one release old.

    A Windows console is frequently cp1252 and the pages are full of `—`, `→` and `✅`.
    Printing straight into one raises `UnicodeEncodeError` half a page in.
    """
    (docs_dir / "USAGE.md").write_text("# Usage\n\nit — works → always ✅\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    )
    from gflow_cli import cli_docs

    rendered = cli_docs._console_safe("it — works → always ✅")
    assert rendered.encode("cp1252")  # the assertion IS that this does not raise
    assert "works" in rendered and "always" in rendered


def test_console_safe_is_a_no_op_on_a_utf8_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    )
    from gflow_cli import cli_docs

    assert cli_docs._console_safe("it — works → always ✅") == "it — works → always ✅"


# --- --json -----------------------------------------------------------------


def test_topics_json_lists_every_page(docs_dir: Path) -> None:
    payload = json.loads(_run("--json").output)
    assert {t["topic"] for t in payload["topics"]} == {
        "usage",
        "user-guide",
        "configuration",
        "index",
    }
    assert all(t["path"].startswith("docs/") for t in payload["topics"])


def test_page_json_carries_the_content(docs_dir: Path) -> None:
    payload = json.loads(_run("usage", "--json").output)
    assert payload["topic"] == "usage"
    assert payload["path"] == "docs/USAGE.md"
    assert "Command-by-command" in payload["content"]


def test_search_json_reports_positions_and_what_it_held_back(docs_dir: Path) -> None:
    payload = json.loads(_run("--search", "reference", "--json").output)
    assert payload["term"] == "reference"
    assert payload["matches"], payload
    first = payload["matches"][0]
    # The position must be the path that EXISTS — the file name, never the slug.
    assert first["path"] == "docs/USAGE.md:3", first
    assert payload["omitted"] == 0


def test_an_installation_with_no_pages_says_so_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docs_catalog, "_docs_dir", lambda: None)
    assert docs_catalog.topics() == []
    assert _run().exit_code == 0
    assert _run("usage").exit_code == 11
