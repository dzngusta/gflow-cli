# Community Feedback Uplift Implementation Plan

> **For agentic workers:** Run `/gflow:status --feature community-feedback-uplift` to find the next
> unchecked task. Implement one task at a time, one workstream per PR. Run `/gflow:check` before
> every commit.

**Goal:** Fix what community projects built on gflow-cli ran into, and adopt what they had to build
around it — a clean install that works, sticky defaults, one-step agent setup and spend safety —
without changing any existing default, exit code, command or MCP contract.

**Architecture:** An umbrella plan of independent workstreams, each its own PR to `develop`. WS1 is
fully tasked here. WS6, WS3, WS4 and WS2 get detailed tasks written into this file after their
`/gflow:scenario` pass, and WS2 only after its zero-credit experiment. New behaviour is opt-in and
resolved in one place shared by CLI and MCP; existing defaults (ADR 7: video 9:16) and exit codes stay.

**Evidence:** community projects that build on gflow-cli (three documented install and usage
workarounds), alternative tools that advertise one-command setup and credit ceilings, repository
traffic (issue #639 is the most-read page after the home page) and PyPI downloads. Details are kept
out of this public file.

**Predict verdict:** STOP as first drafted → **CAUTION, confidence 6/10** after the revisions below
(5-persona review, 2026-09-14, against `develop` 7a44dff6). Hard STOPs removed: WS2 redesigned and
gated on an experiment; the OmniRoute pitch deferred behind prerequisites; WS9 deferred.

**Risk register:**
| Severity | Risk | Mitigation |
|---|---|---|
| High | A missing optional dependency fails **after** a paid clip (true for `av` today; would become true for Pillow with a naive lazy import) | Pre-flight `find_spec("av")`/`find_spec("PIL")` in `_run_chain` before `--dry-run` and the confirm prompt (WS1) |
| High | Onboarding improvements lead new users into a login that fails for accounts served `flow.google.com` (#791, fix in #793) | WS4 ships only after the #791 fix is released |
| High | Spend cap built on a balance that cannot be read on the host our profiles are served (#795), or on reads that launch Chrome and collide with the profile lease | WS2 uses Flow's declared per-model unit cost (the `video extend` pre-flight pattern), gated on a zero-credit experiment; fails closed when a cap is set and the price is unknown |
| High | A sticky project routes paid generations or uploads into the wrong project, including via a `.env` in a cloned directory | Explicit flag always wins; effective value **and its source file path** are shown pre-submit, in `--json`, MCP results and `gflow doctor`; validated locally before any browser launch |
| Medium | MCP `tools/list` schema defaults change (image aspect `1:1` in MCP vs `9:16` in CLI) | Keep schema defaults; resolve a setting only when the parameter is omitted **and** the setting is set; record the existing drift |
| Medium | `--dry-run` loses its "instant, no browser, cannot spend" contract | No balance or price reads in `--dry-run`; print `balance unknown` as `video extend` does |
| Medium | Hand-editing Claude Code's live config races the running app | Register through `claude mcp add --scope user`; print the command when `claude` is not on PATH |
| Low | Queue payload keys accepted but never read (codec keeps unknown keys) | Daemon-enforcement tests, not codec round-trip tests alone |

---

## Non-breaking contract (tick on every PR)

- [ ] No existing default changes. Video aspect stays 9:16; no project is implied unless configured.
- [ ] No exit code changes meaning; prefer existing typed errors. A new code (39) only if the
      workstream's scenario shows agents cannot branch on an existing `type`.
- [ ] No CLI option removed or renamed; new options optional.
- [ ] MCP tools only gain optional parameters; existing `tools/list` defaults and payload keys unchanged.
- [ ] No SQLite migration unless a scenario proves `metadata_json` cannot carry the data.
- [ ] `--json` outputs only gain fields — covered by field-level tests.
- [ ] `--dry-run` stays browser-free and spend-free.
- [ ] The pre-existing suite passes with no edits to existing assertions (or the PR explains why an
      assertion was wrong).

## Workstreams and gates

| Order | WS | What | Gates before code |
|---|---|---|---|
| 1 | **WS1** | Optional-dependency pre-flight + Pillow in `[chain]` + install smoke in `resolve-drift` | Issue → Bug Lane (cause proven) |
| 2 | — | Land #793 (#791 migrated login) and progress #795 (balance on migrated host) | Existing tracks — prerequisites, not duplicated here |
| 3 | **WS6** | Papercuts, folded into onboarding issue #601 | `/gflow:scenario` (error text is a mirror axis) |
| 4 | **WS3** | Opt-in sticky defaults via Settings | `/gflow:scenario` |
| 5 | **WS4** | Agent setup, docs-first | #791 fix released; `/gflow:scenario` |
| 2b | **WS10** | Plugin marketplace + distribution catalog (maintainer priority) | `/gflow:scenario` for the plugin; live install check |
| 6 | **WS2** | Spend cap on declared unit cost | Experiment done 2026-09-14 (price readable pre-submit) → `/gflow:scenario` |
| 7 | **WS8** | OmniRoute pitch (draft, private) | #791 released, t2v spike over `gflow serve` |
| — | **WS5** | Ledger | Folded: `gflow data` already records operations and `unit_cost` |
| — | **WS7** | #639 migrated-host parity | Own track |
| — | **WS9** | `oss-ops ecosystem` automation | Deferred until the review is run by hand a third time (maintainer may override) |

---

## WS1 — Optional-dependency pre-flight and Pillow

**Proven cause:** `src/gflow_cli/media.py:26` imports `PIL` at module level, but Pillow is declared
only in the `dev` group — not in `[project.dependencies]` nor the `chain` extra that `media.py`'s own
docstring points users to. `cli_video.py:942` imports `chain`, which imports `media`, before any client
exists, so today a clean install fails `gflow video chain` early with a raw `ModuleNotFoundError`
(exit 1) and no remediation. The sibling dependency `av` is imported lazily inside `_decode_frame`
(`media.py:80`), so a missing `av` fails only **after link 0 is generated and paid for**
(`chain.py` calls the extractor after the link completes). `video chain` has no MCP twin
(`tests/mcp/test_cli_parity.py`: "chain pipeline — not yet ported"). CI's `resolve-drift` job already
installs the package without the dev group but never imports every module.

**Decision:** add `pillow` to the `chain` extra; import `PIL` lazily in `media.py` (type under
`TYPE_CHECKING`); add a pre-flight that checks `av` and `PIL` with `importlib.util.find_spec` in
`_run_chain` **before** `--dry-run` and the confirm prompt, raising `FrameExtractionError` (exit 20,
existing) whose remediation names `gflow-cli[chain]` and both packages. Rejected: Pillow as a hard
runtime dependency (only the optional chain feature needs it); a new CI job and an AST import scan
(`resolve-drift` covers the class of bug more cheaply).

### Task 1.1 — Red tests

**Files:** `tests/test_media.py`, `tests/test_chain.py` (or the chain CLI test module)

**Steps:**
- [ ] `gflow_cli.media` imports when `PIL` is unimportable (`sys.modules` patch).
- [ ] `gflow video chain <file> --dry-run` without `av` → exit 20, remediation names `gflow-cli[chain]`,
      no client created, no browser launched.
- [ ] Same without `PIL`.
- [ ] Same without either, on the confirm path (not only `--dry-run`): exits before the prompt.
- [ ] A one-link chain does not require the extra (no frame extraction happens) — confirm the current
      behaviour first and pin whichever is correct.

**Tests created (red):**
- [ ] `test_media_imports_without_pillow`
- [ ] `test_chain_preflight_rejects_missing_av_before_spend`
- [ ] `test_chain_preflight_rejects_missing_pillow_before_spend`
- [ ] `test_frame_extraction_remediation_names_chain_extra_and_both_packages`

### Task 1.2 — Fix

**Files:** `pyproject.toml` (`chain = ["av>=12", "pillow>=12.3.0"]`), `uv.lock`,
`src/gflow_cli/media.py` (lazy guarded `PIL` import), `src/gflow_cli/chain.py` or `cli_video.py`
(pre-flight next to `reject_unusable_links`), `src/gflow_cli/errors.py` (`FrameExtractionError`
remediation)

**Steps:**
- [ ] Implement; Task 1.1 green.
- [ ] `/gflow:check` green, including step 1b (remediation text is a mirror axis; confirm no MCP tool
      states otherwise).

### Task 1.3 — Install smoke in `resolve-drift`

**Files:** `.github/workflows/ci.yml` (`resolve-drift` job)

**Steps:**
- [ ] After `uv pip install --upgrade .`: import every module via `pkgutil.walk_packages`, skipping
      `gflow_cli.__main__`; run `gflow video chain --help`.
- [ ] Install `.[chain]` and assert `import av, PIL`.
- [ ] Keep hardening: actions pinned by SHA, `persist-credentials: false`, no `${{ github.* }}` inside
      `run:`, no shared uv cache restore (`tests/scripts/test_workflow_hardening.py` green).
- [ ] Demonstrate once that the step fails with Pillow removed from the extra, then restore.

### Task 1.4 — Docs, changelog, release

**Files:** `CHANGELOG.md` (`Fixed`), `docs/USAGE.md` (chain install note names Pillow),
`KNOWN_ISSUES.md` (entry for users on ≤0.73.2: install `gflow-cli[chain]` plus `pillow`)

**Steps:**
- [ ] Changelog quotes the symptom (`No module named 'PIL'`) and the paid-clip `av` case now caught early.
- [ ] Patch release via `/gflow:release`; afterwards verify on PyPI:
      `uvx --isolated --from "gflow-cli[chain]==<new>" python -c "import gflow_cli.media, av, PIL"` and
      `uvx --isolated --from gflow-cli==<new> gflow video chain x.jsonl --dry-run` → exit 20.

**E2E / Iron Law:** no Flow surface; the pre-flight runs before any client. The re-runnable checks are
the offline tests and the `resolve-drift` step.

---

## WS6 — Papercuts (fold into #601)

Outline — detailed tasks after `/gflow:scenario`:
- [ ] `ProfileLockedError`: improve the `remediation_hint` at the real raise sites
      (`profile_lease.py`, `client.py`), not `_default_remediation` (unused by them). MCP picks it up
      through `_gflow_error_dict`; the canary keys on the class name, so wording is safe.
- [ ] `cookie_decryption_failed_falling_back_to_playwright` (`auth/cookies.py:196`, INFO): move to DEBUG
      with `exc_type` (class name only); the failure that matters already raises.
- [ ] `docs/USAGE.md`: a first-run path for `video chain`, `scene`, `movie`.
- [ ] Present `gflow data` as the generation ledger (operations and `unit_cost` are already recorded).
- [ ] Say `ffroliva/gflow-cli` where the bare name is ambiguous (README, catalogs, posts).

## WS3 — Opt-in sticky defaults

Outline — detailed tasks after `/gflow:scenario`:
- [ ] **First, reproduce and fix the existing gap:** `GFLOW_CLI_PROJECT_NAME` set in `.env` does not reach
      Click's `envvar=` (reproduced: `get_settings()` reads `.env`, `os.environ` does not), while
      `.env.template` tells users to put it there. Red test, then resolve it through `Settings`.
- [ ] Settings `GFLOW_CLI_PROJECT_ID`, `GFLOW_CLI_IMAGE_ASPECT`, `GFLOW_CLI_VIDEO_ASPECT` in `config.py`
      (unset → today's behaviour).
- [ ] One resolver returning value **and source** (flag / env / `.env` path / built-in), in a non-CLI
      module following `profile_store.resolve_profile`; project ids validated with the existing
      `routes._PROJECT_ID_RE`; a stale id fails against the local catalog before any browser launch.
- [ ] CLI: option defaults become `None` with help text stating the fallback (no misleading
      `show_default`); the five `default="9:16"` literals in `cli_video.py` route through the resolver.
- [ ] MCP: keep `tools/list` defaults; when a parameter is omitted, resolve at queue time and write the
      concrete value into the payload (never resolve in the codec). Document that a client-launched
      server reads `$GFLOW_CLI_HOME/.env` or the client's `env` block, not a project `.env`.
- [ ] Security: show the resolving file path; decide in scenario whether `GFLOW_CLI_PROJECT_ID` from a
      CWD `.env` requires confirmation or is ignored unless also in `$GFLOW_CLI_HOME/.env`.
- [ ] Discoverability: `project_source`/`aspect_source` in `--json`, MCP `params`, and `gflow doctor`
      `info` findings (exit 33 semantics unchanged).
- [ ] Precedence tests include #792 (`--project` required on migrated accounts) and #799 (agent-only
      composer exit 25 with `--project`).
- [ ] E2E: zero-credit `e2e_image` run with `GFLOW_CLI_PROJECT_ID` lands in that project.

## WS4 — Agent setup, docs-first (after the #791 fix is released)

Outline — detailed tasks after `/gflow:scenario`:
- [ ] README and `docs/MCP.md`: `claude mcp add --scope user gflow -- gflow mcp run`, plus the
      `--no-spend` variant, with an explicit note that the server can spend credits.
- [ ] `gflow mcp setup --target claude-code`: `shutil.which("claude")` then `claude mcp add --scope user`
      with a timeout; otherwise print the exact command. Never edit Claude Code's config file directly;
      respect `CLAUDE_CONFIG_DIR`. Offer the `--no-spend` registration.
- [x] Spike (2026-09-14, installed plugins on the maintainer machine): Claude Code loads skills a
      plugin ships under `skills/<name>/SKILL.md` without a manifest field; a repo becomes installable
      through `.claude-plugin/marketplace.json` (`"source": "./"` or a subfolder); plugins may declare
      `mcpServers`. **Catch:** this repo's `skills/` also holds maintainer-only skills (`release`,
      `check`, `pr-council-review`, …) — pointing a plugin at the repo root would ship them to users.
- [ ] Skills: a dedicated plugin folder (e.g. `plugins/gflow/`) containing only `gflow-cli` and
      `video-production`, relative doc links rewritten to absolute URLs, plus
      `.claude-plugin/marketplace.json` at the repo root pointing at it. No `gflow skill install`
      command and no wheel bundling. Delivered by WS10.
- [ ] No `--target codex` (already `codex plugin add gflow@gflow-cli`); `cursor` only if verified.
- [ ] MCP parity: `mcp setup` remains a recorded CLI-only exemption.

## WS2 — Spend cap on declared unit cost

- [x] **Experiment (zero credits) — done 2026-09-14**, see
      `docs/superpowers/spikes/2026-09-14-credits-on-migrated-host.md`. On `flow.google.com`:
      the **declared price is readable before submit** from the composer settings pane
      ("Generating will use N credits", follows mode/model/count; 0 for an image model, 12 for
      Omni 1.1 Flash in the 2026-09-05 spike). **No price was found on the wire** and **no balance
      was found anywhere**; the labs credits route returns 401. So: a cap on declared price is
      buildable now; a balance comparison stays blocked on #795.
- [ ] Before scenario: re-measure the video cost line per video model and for x2–x4 (free:
      select, read, revert — nothing submitted), and find a structural anchor for the line.
- [ ] Outline for `/gflow:scenario`:
  - `--max-credits` / `GFLOW_CLI_MAX_CREDITS` on `t2v`, `i2v`, `r2v`, `video chain`, `video extend`:
    before each submit, read the declared cost (settings pane on `flow.google.com`, which the
    composer already opens to set model and count; `creditMapping` on labs; the extend pre-flight
    as today) and refuse when `spent_so_far + declared_cost > cap`; accumulate the declared cost
    per started operation. No balance comparison on `flow.google.com` until #795 locates one.
  - Fail closed: cap set and declared cost unreadable → refuse before submit with remediation.
  - `--dry-run` stays browser-free: show the cap and `balance unknown`.
  - Chain: a cap hit mid-run surfaces as `ChainPartialError` (exit 21) with the cap as the reason, so
    `--resume-from` guidance survives; decide in scenario whether single-op refusal reuses
    `InsufficientCreditsError` (37) or needs a distinct type.
  - MCP: a per-process cumulative budget for `gflow mcp run` / `gflow serve` (the credit burn over MCP
    is a sequence of calls) plus optional per-call `max_credits`; daemon-enforcement tests, not only
    codec round-trips.
  - No schema migration: `unit_cost` is already recorded in `metadata_json`.
  - Docs: `CONFIGURATION.md`, `USAGE.md`, `MCP.md`, `KNOWN_ISSUES.md` (cap is on Flow's declared
    price, not on balance accounting).
  - E2E (`e2e_video`, opt-in): a cap below one clip's declared cost refuses before any spend.

## WS10 — Installable everywhere: plugin marketplace + distribution catalog

**Goal:** anyone can install the gflow skill and MCP server in one step from the places agents and
developers already look, and the project is listed wherever that audience discovers tools.

**Gates:** `/gflow:scenario` for the plugin (what a user sees on install; spend consent for the MCP
server), then TDD. The catalog is docs, but every listing must be verified live, never assumed.

- [ ] **Claude Code plugin + marketplace.** `plugins/gflow/.claude-plugin/plugin.json` (name,
      version kept in sync with `pyproject.toml`, description, homepage, license),
      `plugins/gflow/skills/{gflow-cli,video-production}/` (copied or generated from `skills/`,
      never hand-diverged — a generator + drift check like `generate_website_docs.py --check`),
      optional `mcpServers` entry running `gflow mcp run` (decide `--no-spend` default in scenario),
      and `/.claude-plugin/marketplace.json` at the repo root. Tests: manifest schema, version sync,
      skill copies in sync, no maintainer-only skill shipped, relative links rewritten.
- [ ] **Live install check** in a clean Claude Code config: `/plugin marketplace add ffroliva/gflow-cli`
      → `/plugin install gflow@gflow-cli` → skill listed → MCP server listed. Evidence in the PR.
- [ ] **Keep existing channels in sync:** `.codex-plugin/plugin.json` (Codex) and `server.json` /
      MCP registry metadata if present; one version source.
- [ ] **Distribution catalog** — `docs/DISTRIBUTION.md` (public, operational): for each channel the
      audience, submission method (PR / form / CLI / auto-crawl), requirements, status
      (listed / submitted / todo / not eligible), listing URL, owner and last-verified date. Channels to
      research and verify: official MCP Registry, GitHub MCP registry, Smithery, Glama, mcp.so,
      PulseMCP, MCP Market, awesome-mcp-servers lists, Anthropic/Claude plugin and skills
      marketplaces, community skills marketplaces, Codex plugin listings, Cursor directory, VS Code MCP
      gallery, PyPI classifiers/keywords, and the CLI catalogs already listing us (printing-press,
      AI-CLI-Catalog, open-source catalog — refresh stale data). Outreach steps (forms, PRs to other
      repos) are drafted, then submitted only with the maintainer's go-ahead.
- [ ] README + `docs/MCP.md`: install badges and one-line install per channel once live.

## WS8 — OmniRoute pitch (private draft)

- [ ] Prerequisites: the #791 login fix is released, and `gflow serve`'s documented token and host
      guidance has been re-verified end to end.
- [ ] Spike: t2v end-to-end over `gflow serve` on loopback with the server token; record latency,
      one-job-per-account behaviour, timeout needs (≥600 s) and the tasks-extension behaviour.
- [ ] Draft the pitch privately (maintainer's repo), stating: the documented host and token setup, one
      account and one concurrent job per profile, multi-minute calls, headed browser on the user's
      machine, Google ToS risk. Maintainer decides whether to post.

---

## Definition of done (umbrella)

- [ ] WS1 released; `resolve-drift` install smoke green on `develop`
- [ ] Each of WS6, WS3, WS4, WS2 merged with its scenario record, `/gflow:check` green, council GREEN,
      SonarCloud green, and the e2e evidence its surface requires
- [ ] Non-breaking contract ticked on every PR
- [ ] `CHANGELOG.md` `[Unreleased]` updated per PR
- [ ] Docs updated per workstream (`USAGE.md`, `CONFIGURATION.md`, `MCP.md`, `KNOWN_ISSUES.md`)
- [ ] BDD features cover every Critical and High scenario from each `/gflow:scenario`
- [ ] No `# TODO` in any diff without a tracked issue link
