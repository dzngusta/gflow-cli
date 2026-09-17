"""`gflow docs` — the documentation, reachable from the terminal (#861).

Three shapes, all read-only, all offline: list the topics, print one, or search for the
line that answers a question. No network, no account, no credits, no database.

**No MCP twin yet — deferred with a shape, not excluded on principle** (scenario #14,
registered in `tests/mcp/test_cli_parity.py::_MCP_EXEMPT` so the decision is enforced
rather than asserted here). "Agents do not need it" would be false: the consumer that
filed #861 *is* an agent. What is true is that documentation is not a tool call. MCP
models documents as **resources**, and wrapping `docs --search` as a tool would hand an
agent a second, worse way to read prose its tool descriptions already carry.

The upgrade path is a resources provider over `gflow_cli.docs_catalog`, which is why every
decision — what a topic is, how a name resolves, how search ranks — lives in that module,
Click-free and returning data. This file only renders.
"""

from __future__ import annotations

import sys
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from gflow_cli import docs_catalog, json_output
from gflow_cli._cli_helpers import run_with_handlers
from gflow_cli.errors import ConfigurationError

console = Console()


def _console_safe(text: str) -> str:
    """*text*, guaranteed to survive this console's encoding.

    The pages are full of `—`, `→` and `✅`, and a Windows console is frequently cp1252.
    Printing straight into one raises `UnicodeEncodeError` and the command dies having
    printed half a page — which is the exact shape of #846, shipped one release ago in a
    decoration that had only ever run on a UTF-8 dev machine. A round-trip through the
    stream's own encoding with replacement cannot raise, and is a no-op where the console
    is UTF-8 (which is most of them).
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except LookupError:  # pragma: no cover - an encoding name Python cannot resolve
        return text.encode("ascii", errors="replace").decode("ascii")


@click.command("docs")
@click.argument("topic", required=False)
@click.option(
    "--search",
    "term",
    default=None,
    metavar="TERM",
    help="Find the lines mentioning TERM across every page, curated answers first.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON.")
def docs(topic: str | None, term: str | None, as_json: bool) -> None:
    """Browse gflow's own documentation.

    \b
      gflow docs                       list every topic
      gflow docs usage                 print one page
      gflow docs --search duration     find the line that answers a question

    Entirely offline and read-only: the pages ship inside the package.
    """
    run_with_handlers(lambda: _run(topic, term, as_json), cli_command="docs", as_json=as_json)


async def _run(topic: str | None, term: str | None, as_json: bool) -> None:
    if topic and term:
        raise ConfigurationError(
            detail=(
                "pass a topic or --search, not both — `gflow docs <topic>` prints one "
                "page, `gflow docs --search <term>` looks across all of them"
            ),
        )
    if term is not None:
        _emit_search(term, as_json=as_json)
        return
    if topic:
        _emit_page(topic, as_json=as_json)
        return
    _emit_topics(as_json=as_json)


def _emit_topics(*, as_json: bool) -> None:
    found = docs_catalog.topics()
    if as_json:
        json_output.emit(
            {
                "topics": [
                    {
                        "topic": t.slug,
                        "title": t.title,
                        "summary": t.summary,
                        "path": t.repo_path,
                    }
                    for t in found
                ]
            }
        )
        return
    if not found:
        console.print("[yellow]No documentation is bundled with this installation.[/]")
        return
    table = Table(title=f"gflow documentation ({len(found)} topics)")
    table.add_column("topic", style="bold", no_wrap=True)
    table.add_column("what it covers", overflow="fold")
    for entry in found:
        table.add_row(_console_safe(entry.slug), _console_safe(entry.summary or entry.title))
    console.print(table)
    console.print(
        "  Show one: [bold]gflow docs <topic>[/]   Find a line: [bold]gflow docs --search <term>[/]"
    )


def _emit_page(topic: str, *, as_json: bool) -> None:
    entry = docs_catalog.resolve(topic)
    body = docs_catalog.read(entry)
    if as_json:
        json_output.emit(
            {
                "topic": entry.slug,
                "title": entry.title,
                "path": entry.repo_path,
                "content": body,
            }
        )
        return
    # Raw Markdown, not rendered: it pipes into a pager or an editor, and an agent reading
    # stdout wants the source rather than box-drawing characters.
    click.echo(_console_safe(body))


def _emit_search(term: str, *, as_json: bool) -> None:
    shown, held_back = docs_catalog.truncate_hits(docs_catalog.search(term))
    if as_json:
        json_output.emit(
            {
                "term": term,
                "matches": [_match_json(m) for m in shown],
                "omitted": held_back,
            }
        )
        return
    if not shown:
        # Exit 0: "nothing mentions that" is a true answer to a valid question, not a
        # failure of the command.
        console.print(f"No page mentions [bold]{_console_safe(term)}[/].")
        return
    table = Table(title=f"'{_console_safe(term)}' — {len(shown)} match(es)")
    table.add_column("where", style="bold", no_wrap=True)
    table.add_column("line", overflow="fold")
    for match in shown:
        table.add_row(_console_safe(match.position), _console_safe(match.text))
    console.print(table)
    if held_back:
        console.print(f"  … and {held_back} more. Narrow the term, or read the page.")


def _match_json(match: Any) -> dict[str, Any]:
    return {
        "topic": match.topic,
        "path": match.position,
        "line": match.line_no,
        "text": match.text,
        "curated": match.curated,
    }
