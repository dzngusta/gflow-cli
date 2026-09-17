"""The documentation catalog behind `gflow docs` (#861) — enumeration, lookup, search.

Pure: no network, no account, no database, no Click. Everything it reads is text that
shipped inside this package.

**Why this exists.** 126 pages in `docs/` and nothing in the CLI points at any of them, so
at the moment of use the knowledge is unreachable and the reader guesses. The failure that
filed #861 was a run with `--duration 10` against a host that offers reference-to-video at
8 s only. That rule was already written down -- inside a 4 000-character bullet in
`MCP.md`. Which is why :func:`search` returns a **line with its position**, windowed around
the match: answering "it is in MCP.md" would leave the reader exactly where they started.

**Why no manifest.** A hand-maintained topic list drifts the first time someone adds a
page. The directory listing is the list, at build time (`hatch_build.py` globs it) and at
read time (:func:`topics` iterates it). There is nothing to keep in sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from gflow_cli.errors import ConfigurationError

#: The directory `hatch_build.py` installs the pages into, inside this package.
_PACKAGE_DOCS = "_docs"

#: Where the pages live in the repository — printed so a reader can find the source,
#: and the prefix used for the `file:line` positions search reports.
REPO_DOCS_DIR = "docs"

#: A curated row of `INDEX.md` § Topic shortcuts:
#: `**"How do I X?"** → [LABEL](TARGET.md#anchor) trailing prose`
#: These are the highest-signal lines in the whole tree — each one was written to *be* an
#: answer — so they are searched first and ranked above raw body text.
_SHORTCUT = re.compile(r'^\*\*"(?P<question>.+?)"\*\*\s*(?:→|->)\s*(?P<answer>.+)$')

#: The first Markdown link inside a shortcut's answer half.
_FIRST_LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")

#: How much of a matching line to show. `MCP.md` has single lines over 4 000 characters;
#: printing one whole is the "go read the file" answer with extra steps.
_SNIPPET_WIDTH = 160

#: Body hits returned before the caller is told there are more. Enough to choose from,
#: few enough to read.
_MAX_BODY_HITS = 20


@dataclass(frozen=True, slots=True)
class Topic:
    """One documentation page."""

    slug: str
    """Lowercase, dash-separated, no suffix — `REFERENCE_STRATEGIES.md` → `reference-strategies`."""

    file_name: str
    """The page's own file name, e.g. `REFERENCE_STRATEGIES.md`."""

    title: str
    """The first `# ` heading, or the file name when a page has none."""

    summary: str
    """The first line of prose under the title. Empty when the page opens with a table."""

    @property
    def repo_path(self) -> str:
        """Where to find this page in the repository."""
        return f"{REPO_DOCS_DIR}/{self.file_name}"


@dataclass(frozen=True, slots=True)
class Match:
    """One search hit."""

    topic: str
    """The slug of the page it was found in."""

    file_name: str
    """That page's real file name — `MCP.md`, not `mcp.md`. The slug is for typing at the
    command line; a position a reader is meant to open has to be the path that exists."""

    line_no: int
    """1-indexed line within that page."""

    text: str
    """The matching line, windowed around the term."""

    curated: bool
    """True for an `INDEX.md` § Topic shortcuts row — an answer, not merely a location."""

    score: int = 0
    """Relevance. See :func:`_score`; only meaningful for ordering body hits."""

    @property
    def position(self) -> str:
        return f"{REPO_DOCS_DIR}/{self.file_name}:{self.line_no}"


def _docs_dir() -> Any:
    """The directory holding the pages, or ``None`` when there is none.

    Two sources, in order:

    1. ``gflow_cli/_docs`` — what `hatch_build.py` ships. This is the only one that exists
       for someone who installed from PyPI, which is the whole point of #861.
    2. the repository's own ``docs/`` — because the build hook runs at *build* time, so an
       editable install (`uv sync`, every test run, every contributor) has no ``_docs``.
       Without this fallback the command would work for users and be dead in development,
       which is the reverse of the usual bug and twice as confusing.

    Resolved through ``importlib.resources`` rather than ``__file__`` so a zipimport or
    frozen environment still reads (scenario #5). The repository fallback is derived from
    the package's own location and never from user input.
    """
    try:
        shipped = resources.files("gflow_cli").joinpath(_PACKAGE_DOCS)
        if shipped.is_dir():
            return shipped
    except (ModuleNotFoundError, TypeError):  # pragma: no cover - defensive
        pass
    try:
        checkout = Path(__file__).resolve().parents[2] / REPO_DOCS_DIR
    except IndexError:  # pragma: no cover - defensive
        return None
    return checkout if checkout.is_dir() else None


def _slug(file_name: str) -> str:
    return file_name[:-3].lower().replace("_", "-") if file_name.endswith(".md") else file_name


#: Markdown that carries no meaning once the line is a one-line summary in a table.
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")
_LIST_ITEM = re.compile(r"^(\d+[.)]|[-*+])\s")

#: How much of the first prose line the topic table shows.
_SUMMARY_WIDTH = 90


def _plain(line: str) -> str:
    """*line* with the Markdown taken out: links become their label, emphasis goes.

    A summary column showing `Read [DISCLAIMER.md](../DISCLAIMER.md) first` is worse than
    no summary — it costs the reader the same parsing the raw file would.
    """
    return " ".join(_EMPHASIS.sub("", _LINK.sub(r"\1", line)).split())


def _title_and_summary(text: str) -> tuple[str, str]:
    """The page's `# ` heading and its first line of prose.

    Tolerant by design: a page with no heading, or one that opens with a table, a list or
    a blockquote, still produces a :class:`Topic` — it just has less to say about itself.
    """
    title, summary = "", ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not title:
            if line.startswith("# "):
                title = _plain(line[2:])
            continue
        if line.startswith(("#", ">", "|", "`", "<")) or _LIST_ITEM.match(line):
            continue
        summary = _plain(line)
        if len(summary) > _SUMMARY_WIDTH:
            summary = summary[:_SUMMARY_WIDTH].rstrip() + " …"
        break
    return title, summary


def topics() -> list[Topic]:
    """Every shipped page, by slug. Empty when no docs directory is available."""
    directory = _docs_dir()
    if directory is None:
        return []
    found: list[Topic] = []
    for entry in directory.iterdir():
        name = entry.name
        if not name.endswith(".md") or not entry.is_file():
            continue
        title, summary = _title_and_summary(_read(entry))
        found.append(Topic(slug=_slug(name), file_name=name, title=title or name, summary=summary))
    return sorted(found, key=lambda t: t.slug)


def _read(entry: Any) -> str:
    """A page's text. UTF-8 with replacement: a page that cannot be decoded must still be
    listed and searched, because a catalog that raises is worse than one that is lossy."""
    try:
        return str(entry.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):  # pragma: no cover - defensive
        return ""


def read(topic: Topic) -> str:
    """The full text of a page."""
    directory = _docs_dir()
    if directory is None:  # pragma: no cover - resolve() cannot yield a Topic without one
        return ""
    return _read(directory.joinpath(topic.file_name))


def resolve(name: str) -> Topic:
    """The page *name* refers to.

    Accepts the slug, the file name, either case, and any unambiguous prefix — the three
    forms a reader actually types (`usage`, `USAGE.md`, `ref`).

    **The lookup is a dictionary hit against the enumerated pages; the argument is never
    joined onto a path.** That is what makes `gflow docs ../../../../etc/passwd` an
    ordinary unknown-topic refusal rather than a file read, and it stays true without a
    traversal check to keep correct.
    """
    available = topics()
    if not available:
        raise ConfigurationError(
            detail=(
                "no documentation is available in this installation — the pages ship "
                "inside the wheel, so a source tree without them cannot serve them"
            ),
        )
    key = name.strip().lower()
    if key.endswith(".md"):
        key = key[:-3]
    key = key.replace("_", "-")
    by_slug = {t.slug: t for t in available}
    if key in by_slug:
        return by_slug[key]
    if key:
        starting = [t for t in available if t.slug.startswith(key)]
        if len(starting) == 1:
            return starting[0]
        if len(starting) > 1:
            raise ConfigurationError(
                detail=(
                    f"{name!r} matches {len(starting)} topics: "
                    f"{', '.join(t.slug for t in starting[:8])}"
                    f"{' …' if len(starting) > 8 else ''} — name one of them"
                ),
            )
    raise ConfigurationError(detail=_unknown_detail(name, key, available))


def _unknown_detail(name: str, key: str, available: list[Topic]) -> str:
    near = [t.slug for t in available if key and key in t.slug][:6]
    hint = (
        f" — did you mean {', '.join(near)}?"
        if near
        else " — run `gflow docs` for the list, or `gflow docs --search <term>`"
    )
    return f"no documentation topic named {name!r}{hint}"


def _snippet(line: str, term: str) -> str:
    """*line*, windowed around the first occurrence of *term*.

    `MCP.md` documents the migrated-host duration rule inside a single 4 000-character
    bullet. Returning that line whole is the failure #861 describes, restated as output.
    """
    collapsed = " ".join(line.split())
    if len(collapsed) <= _SNIPPET_WIDTH:
        return collapsed
    at = collapsed.lower().find(term.lower())
    if at < 0:  # pragma: no cover - callers only pass lines that matched
        return collapsed[:_SNIPPET_WIDTH] + " …"
    start = max(0, at - _SNIPPET_WIDTH // 3)
    end = min(len(collapsed), start + _SNIPPET_WIDTH)
    return ("… " if start else "") + collapsed[start:end] + (" …" if end < len(collapsed) else "")


def shortcuts() -> list[tuple[int, str, str]]:
    """`INDEX.md` § Topic shortcuts as ``(line_no, question, target)``.

    Additive, never load-bearing: if `INDEX.md` is missing or its format changes, this
    returns nothing and :func:`search` falls back to body text alone. A curated index is
    worth ranking first and worth nothing to depend on.
    """
    directory = _docs_dir()
    if directory is None:
        return []
    index = directory.joinpath("INDEX.md")
    if not index.is_file():
        return []
    rows: list[tuple[int, str, str]] = []
    for line_no, raw in enumerate(_read(index).splitlines(), start=1):
        row = _SHORTCUT.match(raw.strip())
        if row is None:
            continue
        link = _FIRST_LINK.search(row.group("answer"))
        rows.append((line_no, row.group("question"), link.group("target") if link else ""))
    return rows


_HEADING_BONUS = 10


def _score(line: str, terms: list[str]) -> int:
    """How much a matching line is *about* the terms, rather than merely containing them.

    Two signals: a heading is a section's own claim about itself, so it outranks body
    prose; and a line that names a term repeatedly is discussing it rather than mentioning
    it in passing.

    **What ranking cannot do, measured.** The query in #861 is the bare word `duration`,
    and it has 133 hits. Alphabetical order put a UI-recon document on top. Adding the
    heading bonus put eight `LIVE_VERIFICATION_*` release records on top. The next idea was
    to rank pages that `INDEX.md` routes to above ones it does not -- the repository's own
    statement of what is reference material. That was built and measured, and it is false:
    `INDEX.md` links **93 of the 126 pages**, every release record included, so it
    discriminates nothing. It is not here because it did not work, and this paragraph is
    the reason not to add it again.

    What does work is the query having a second word. `r2v duration` returns five hits with
    the rule first; `duration` alone returns 133 and says so, which is the honest answer to
    a vague question. See `SCENARIO.md` § M2.
    """
    lowered = line.lower()
    occurrences = sum(lowered.count(term) for term in terms)
    return (_HEADING_BONUS if line.lstrip().startswith("#") else 0) + occurrences


def search(term: str) -> list[Match]:
    """Every line mentioning *term*, curated answers first, then by relevance.

    Whitespace splits the query into terms that must **all** appear on the line, so
    `--search "r2v duration"` narrows where a single common word cannot.

    Two passes over the same corpus, deliberately not merged. `INDEX.md`'s shortcut rows
    were each written to answer a question; a body-text hit only says where to look. When
    both exist for one term, showing the body hit first buries the better answer.
    """
    terms = [t for t in term.strip().lower().split() if t]
    if not terms:
        return []
    curated = [
        Match(
            topic="index",
            file_name="INDEX.md",
            line_no=line_no,
            text=_plain(f"{question} -> {target}"),
            curated=True,
        )
        for line_no, question, target in shortcuts()
        if all(t in question.lower() or t in target.lower() for t in terms)
    ]
    seen = {(m.topic, m.line_no) for m in curated}
    body: list[Match] = []
    for topic in topics():
        for line_no, raw in enumerate(read(topic).splitlines(), start=1):
            lowered = raw.lower()
            if not all(t in lowered for t in terms) or (topic.slug, line_no) in seen:
                continue
            body.append(
                Match(
                    topic=topic.slug,
                    file_name=topic.file_name,
                    line_no=line_no,
                    text=_snippet(raw, terms[0]),
                    curated=False,
                    score=_score(raw, terms),
                )
            )
    body.sort(key=lambda m: (-m.score, m.topic, m.line_no))
    return curated + body


def truncate_hits(matches: list[Match]) -> tuple[list[Match], int]:
    """The hits to show and how many were held back. Curated rows are never held back."""
    curated = [m for m in matches if m.curated]
    body = [m for m in matches if not m.curated]
    return curated + body[:_MAX_BODY_HITS], max(0, len(body) - _MAX_BODY_HITS)
