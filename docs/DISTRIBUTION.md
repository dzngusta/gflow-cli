# Distribution channels

Where people can install or discover gflow-cli, what each channel needs, and where we stand.

This is an operational document, not a wish list. **Every row was verified live on its
`last verified` date** — a page fetched, a search run, a schema read. Where something could not be
checked, the row says `UNVERIFIED` and names what blocked it. Do not update a row from memory; if
you cannot re-check it, change the date and mark it stale instead.

**Status vocabulary:** `listed` (we are in it) · `todo` (eligible, not submitted) · `submitted`
(sent, awaiting review) · `not eligible` (cannot be listed as the project is packaged) ·
`passive` (auto-crawled — nothing to submit).

> **Outreach is the maintainer's call.** Every submission below is drafted, never sent
> automatically. Anything that posts to a third party — a form, a PR to another repo, an email —
> waits for an explicit go-ahead.

---

## At a glance

| Channel | Audience | Submit via | Status | Last verified |
|---|---|---|---|---|
| [PyPI](https://pypi.org/project/gflow-cli/) | Python users, every downstream scraper | `uv publish` (release) | listed | 2026-09-14 |
| [Official MCP Registry](https://registry.modelcontextprotocol.io) | Agent devs; feeds other registries | `mcp-publisher` CLI | todo | 2026-09-14 |
| [Glama](https://glama.ai/mcp) | Broad MCP audience (87k servers) | Web form | todo | 2026-09-14 |
| [MCP Market](https://mcpmarket.com/server/gflow-cli) | Consumer discovery | — (crawled us) | **listed** | 2026-09-14 |
| [skills.sh](https://skills.sh/ffroliva/gflow-cli) | Cross-agent skill users | — (telemetry) | **listed** | 2026-09-14 |
| [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | The MCP list (95k★) | PR | todo | 2026-09-14 |
| [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Claude Code (54k★) | Issue | todo | 2026-09-14 |
| [mcpservers.org](https://mcpservers.org/submit) | MCP discovery | Web form (no PRs) | todo | 2026-09-14 |
| [cursor.directory](https://cursor.directory) | Cursor users | Web form | todo | 2026-09-14 |
| [appcypher/awesome-mcp-servers](https://github.com/appcypher/awesome-mcp-servers) | MCP (5.8k★) | PR | todo | 2026-09-14 |
| Claude Code plugin marketplace (ours) | Claude Code users | — (self-hosted) | shipped | 2026-09-14 |
| [claude-community](https://github.com/anthropics/claude-plugins-community) | Claude Code + Cowork | Console web form | todo | 2026-09-14 |
| [cursor.com/marketplace](https://cursor.com/marketplace) | Cursor (curated) | Web form | todo | 2026-09-14 |
| GitHub MCP Registry / VS Code gallery | Copilot, VS Code | Email, after the MCP Registry | todo | 2026-09-14 |
| [Arnon-hs/open-source](https://github.com/Arnon-hs/open-source) | Agent-facing catalog | — (auto) | **listed, stale** | 2026-09-14 |
| [hasnocool/AI-CLI-Catalog](https://github.com/hasnocool/AI-CLI-Catalog) | AI CLI catalog | PR | listed | 2026-09-14 |
| [linny006/mcp-servers-live](https://github.com/linny006/mcp-servers-live) | Auto tracker | — (GitHub topic) | listed, fresh | 2026-09-14 |
| [PulseMCP](https://www.pulsemcp.com) | End users + devs | Closed; auto-ingests | blocked | 2026-09-14 |
| [Smithery](https://smithery.ai) | Hosted MCP | — | **not eligible** | 2026-09-14 |
| [mcp.so](https://mcp.so) | SEO discovery | Web form, paid | todo (low) | 2026-09-14 |
| Codex / ChatGPT Plugins Directory | ChatGPT + Codex | Portal, identity-verified | todo (low) | 2026-09-14 |
| printing-press-library | — | — | **not a listing** | 2026-09-14 |

---

## Priority order

Ranked by reach per hour of work, not alphabetically.

1. **PyPI metadata** — the only channel we fully control, and the summary line is what every
   other catalog copies. Ships free with the next release.
2. **Official MCP Registry** — the one that feeds the others. PulseMCP says so explicitly and
   GitHub's blog says so; it is also the prerequisite for the VS Code gallery.
3. **skills.sh** — already listed with 21 installs. Add the badge; zero submission work.
4. **punkpeye/awesome-mcp-servers** — ~95k★ and everyone else scrapes it.
5. **Glama** — free, repo-based, indexes in minutes, no packaging change.
6. **claude-community** — free, automated review, in front of every Claude Code user.
7. **cursor.directory** — no human gate, and comparable video-generation MCP plugins are listed.
8. **Arnon-hs licence bug** — low traffic, but it misstates our licence in a catalog agents read.
9. Everything below that is optional.

---

## Channels in detail

### PyPI — `listed`

The package page is the single most-copied description we have. Three findings, all fixed in
this change and all taking effect on the **next upload** (PyPI metadata is frozen per release):

- The summary described only image-to-video and never mentioned MCP — half of what the package is.
- `Documentation`, `Repository` and `Changelog` sidebar links were missing (three free clicks).
  All three verified live at HTTP 200. `Funding` was already correct.
- Classifiers were thin. Added `Topic :: Scientific/Engineering :: Artificial Intelligence`,
  `Topic :: Multimedia :: Graphics`, `Topic :: Utilities`, `Typing :: Typed`,
  `Framework :: AsyncIO`, `Framework :: Pydantic :: 2`, `Operating System :: OS Independent`,
  `Intended Audience :: End Users/Desktop`, `Natural Language :: English`,
  `Programming Language :: Python :: 3 :: Only`. Every one was checked against the official
  895-entry trove list — an invented classifier fails the upload outright.

**Open, not done:** the README carries 36 relative links that are dead on PyPI. PyPI renders
`<a href="docs/MCP.md">` verbatim, so a reader lands on `pypi.org/project/gflow-cli/docs/MCP.md`.
Absolutising them fixes it, but `scripts/ci/check_doc_links.py` validates relative targets against
disk and would stop checking them — so the fix is absolutise **plus** teach the checker to map our
own `blob/main/` URLs back to paths. Tracked, not done here.

### Official MCP Registry — `todo`

Schema `2025-12-11`, read live. `ServerDetail` requires `name`, `description`, `version`;
`description` is capped at **100 characters**; `name` must match `^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$`
(exactly one slash) and, under GitHub auth, start with `io.github.ffroliva/`.

`server.json` is in this change, and `README.md` carries the ownership token the registry looks
for (`mcp-name: io.github.ffroliva/gflow-cli`, in an HTML comment so it does not render).
`tests/test_server_json.py` pins version lockstep, the description cap, the name pattern, the
token, and that the advertised command exists.

**The blocker that would have shipped a broken listing.** The registry builds `uvx <identifier>`
from the PyPI identifier and has no field for a differently-named executable. Measured:

```
$ uvx --isolated gflow-cli@0.74.0 --version
Use `uvx --from gflow-cli <EXECUTABLE-NAME>` instead.
```

`[project.scripts]` defined only `gflow` and `flow`. A `gflow-cli` console script is added here, so
`uvx gflow-cli mcp run` works — which is also what a user types first, the package being what they
just installed.

Publish sequence (needs the next release on PyPI first, so the token is in the published README):

```
mcp-publisher init
mcp-publisher login github     # namespace becomes io.github.ffroliva/*
mcp-publisher publish
```

### Glama — `todo`

*"On the servers page, click Add MCP Server and fill in: the GitHub repository URL, a display name
and short description."* Automated licence, security and health checks; most submissions index
within minutes. A `glama.json` in the repo controls display name, description and category — worth
adding if the health check stalls on a browser-driving server. Confirmed not listed:
`glama.ai/mcp/servers/ffroliva/gflow-cli` → 404.

### MCP Market — `listed`, nobody submitted it

`https://mcpmarket.com/server/gflow-cli` → HTTP 200, titled *"Gflow CLI: Programmatic AI Video &
Image Generation"*, author `ffroliva`, category Developer Tools. The copy reads machine-generated,
so this was crawled. **Action: audit the copy for accuracy, not submit.** The page shows 112 stars
against 198 live, so its snapshot is stale.

### skills.sh — `listed`, and we did not know

`https://skills.sh/ffroliva/gflow-cli` — **16 skills, 21 installs**, `npx skills add
ffroliva/gflow-cli`. Operated by Vercel; indexed automatically from anonymous install telemetry,
so there is nothing to submit.

**It has the same curation problem the plugin channels had.** It indexes the repo's `skills/`
directory, so `release`, `check` and `pr-council-review` are listed as installable skills. The
plugin work curates the three manifest-driven channels; skills.sh reads the directory itself, so
curating it would mean moving files. Recorded, not fixed.

Free win: add the badge and the `npx skills add ffroliva/gflow-cli` line to the README.

### awesome lists — `todo`

- **punkpeye/awesome-mcp-servers** (~95k★). Fork → edit `README.md` → PR; an agent-authored PR
  should carry `🤖🤖🤖` in the title for the fast-track. Category `### 🎥 Multimedia Process`,
  alphabetical by `owner/repo` — our line goes between `editmamei/editmamei` and
  `FileToPDF/filetopdf-mcp`. Legend: 🐍 Python, 🏠 local service, 🍎🪟🐧 platforms. **Not** 🎖️, which
  means an official implementation.
- **hesreallyhim/awesome-claude-code** (54k★). Submit an *issue*, not a PR. Gate: ≥100 stars or
  ≥14 days old with active commits — we have 198. One resource per submission, no review contract.
- **appcypher/awesome-mcp-servers** (5.8k★). PR, appended to the bottom of a category. There is no
  multimedia category, so we would land in `## 🤝 AI Services` next to RAG and chat servers — a
  poor fit. Do it after the others.
- **mcpservers.org** (via wong2's list). **PRs are explicitly refused**; the web form at
  `mcpservers.org/submit` is the only door.

Searched each for `gflow`, `ffroliva`, `veo`, `google flow` — none listed.
`TensorBlock/awesome-mcp-servers` was checked by README only and its README is small enough to
suggest category files exist, so treat its "not listed" as **UNVERIFIED**.

### Claude Code plugin marketplaces

Our own marketplace ships in this repo — see [MCP.md](MCP.md) for the install lines.

- **`claude-plugins-official`** — *"There is no application process"*. Not applicable.
- **`claude-community`** — submit at `https://platform.claude.com/plugins/submit` (the Console
  form; the claude.ai form needs a Team/Enterprise org, the Console one works for solo
  maintainers). Approved plugins are pinned to a commit SHA and the catalog syncs nightly. PRs
  against the repo are auto-closed. Prerequisite: `claude plugin validate . --strict` passes —
  it does.
- **claudemarketplaces.com** — auto-crawls skills.sh, GitHub and MCP registries. `passive`.

### Cursor — `todo`

- **cursor.directory** (community, 5,429 plugins): web form at `/plugins/new`, sign in with
  GitHub, paste a repo URL. Components are auto-detected **by path**: `.mcp.json`, `rules/*.mdc`,
  `skills/*/SKILL.md`, `agents/*.md`. Our `skills/` layout already matches; the plugin work adds
  `plugins/gflow/.mcp.json`, but auto-detect looks at the **repo root**, so a root `.mcp.json` may
  be needed — **UNVERIFIED**, check after submitting.
- **cursor.com/marketplace** (official, curated, 240 entries): needs a root `plugin.json` or
  `.cursor-plugin/plugin.json`, a logo committed to the repo, and Cursor-team review.
- Note: `cursor.com/directory` serves the generic homepage — it is not a directory.

### GitHub MCP Registry / VS Code gallery — `todo`

VS Code's MCP gallery **is** the GitHub MCP Registry (`chat.mcp.gallery.enabled`, backed by
`api.github.com/copilot/mcp_registry`). Two stages: publish to the official MCP Registry (self-
serve), then email `partnerships@github.com` to request inclusion. Curated, 252 servers, weighing
stability, security practices and ecosystem value. Not listed (all four search terms → 0).

**UNVERIFIED:** whether GitHub now auto-ingests from the official registry, making the email
unnecessary. Its 2025 launch post says servers *"will automatically appear"*; the current how-to
still says to email. The API needs a Copilot-scoped token to settle it.

### Catalogs already listing us

- **Arnon-hs/open-source** — `listed, stale`, **twice**
  ([mcp/](https://github.com/Arnon-hs/open-source/blob/main/mcp/ffroliva-gflow-cli.md),
  [content-creation/](https://github.com/Arnon-hs/open-source/blob/main/content-creation/ffroliva-gflow-cli.md)).
  Stars `111` → **198**; forks `32` → **54**; last push `2026-08-14`/`2026-09-05` → **2026-09-14**.
  Worse, the Russian summary says *«доступен под лицензией Python»* — "available under the Python
  licence". **We are MIT.** It looks like the `language` field was mapped into the licence
  sentence, which would affect every Python project in the catalog. Cards are machine-generated
  with no `CONTRIBUTING.md`, so a content PR would be overwritten; the route is an issue asking
  them to re-run their scout and fix the licence mapping.
- **hasnocool/AI-CLI-Catalog** — `listed`, accurate. `catalog.json` and the README table agree,
  and every flag checks out (MCP yes, daemon yes, subscription auth yes, no API key, no local
  models). Only `"last_verified": "2026-08-09"` is stale. Optional one-line PR.
- **linny006/mcp-servers-live** — `listed, fresh`. Auto-indexes the GitHub topic `mcp-server`
  every 15 minutes; our page was one star behind live. Nothing to do — but it confirms the
  `mcp-server` topic is doing passive discovery work.

### Not eligible / not a listing

- **Smithery** — accepts only hosted JS uploads, an external public HTTPS endpoint, or a `.mcpb`
  stdio bundle. **PyPI is not a supported path.** A hosted endpoint is a non-starter for a server
  that drives a local Chrome profile and spends the user's credits.
- **PulseMCP** — submissions paused since 2026-09-03, and their own guidance is to publish to the
  Official MCP Registry, which they will ingest automatically. Doing #2 covers this for free.
- **mcp.so** — the only confirmed path is a $39 "publish immediately" tier. Whether a free
  reviewed queue exists is **UNVERIFIED** (the page gates it behind sign-in). Low priority.
- **Codex / ChatGPT Plugins Directory** — an MCP-backed submission requires a **public MCP server
  URL** for their scanner. Ours is local stdio. Only the "Skills only" path is open, and it needs
  verified developer identity plus 5 positive and 3 negative test cases. Low payoff.
- **printing-press-library** — **we are not listed.** Our single mention is one line under
  *"Sources & Inspiration"* in the README of `flow-pp-cli`, a competing Go CLI that studied us.
  There is no entry to refresh and no submission process. Competitive intelligence, not a channel.

---

## Keeping this honest

- Re-verify before acting on any row older than ~30 days. These platforms change monthly: PulseMCP
  closed submissions, Smithery dropped to three release types, and `cursor.com/directory` stopped
  being a directory — all within the window this document covers.
- When a submission lands, update `status`, `listing URL` and `last verified` in the same change.
- Every `UNVERIFIED` above is a real gap, not a hedge. Closing one is a small, well-defined task.
