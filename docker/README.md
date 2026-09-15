# Running gflow-cli in a container

**Status: measured, partially.** The plumbing works and the browser presents clean. The one-time
Google sign-in inside a container has **not** been run, and neither has a generation. Evidence and
exact readings: [`docs/superpowers/spikes/2026-09-15-container-transport-viability.md`](../docs/superpowers/spikes/2026-09-15-container-transport-viability.md).

Do not read this as "containerised gflow is supported". Read it as "here is the protocol, here is
precisely how far it has been verified, and here is what is left to try".

## The shape

**The container is disposable. The volume is not.** Everything that identifies you — the Chrome
profile, `GFLOW_CLI_HOME`, the SQLite catalog — lives in the named `gflow-auth` volume, so the
image can be rebuilt or upgraded without signing in again.

## Two things that are not optional

**Real Google Chrome, not Chromium.** `browser_manager.is_playwright_chrome_channel_available()`
accepts exactly one Linux path for `channel="chrome"`: `/opt/google/chrome/chrome`. That is where
the `google-chrome-stable` .deb installs. A distro Chromium does **not** satisfy it, and
generation needs a real-Chrome profile.

**`xauth` alongside `xvfb`.** `xvfb-run` fails with `xauth command not found` without it. This
cost the spike an arm.

## Xvfb is not a headless workaround

Xvfb is a real X server with no attached monitor. Chrome runs genuinely **headed** against it.
That is categorically different from Chrome's `--headless` mode, which is what Google's auth and
reCAPTCHA stack rejects. Measured inside the container with gflow's own launch arguments:

```
REAL CHROME launched   : 153.0.8010.36
navigator.webdriver    : None
headless UA marker?    : False
```

## Use

```bash
# 1. Build
docker compose build

# 2. Sign in ONCE, into the volume. This is the only step a headless box cannot do —
#    it needs a real display.
#    Linux:  xhost +local: && docker compose run --rm login
xhost +local: && docker compose run --rm login

# 3. Everything else runs headed under Xvfb against that volume
docker compose run --rm gflow                      # gflow auth status
docker compose run --rm gflow gflow credits user   # read-only, $0

# 4. The MCP server, for an agent on the host
export GFLOW_CLI_DAEMON_TOKEN=$(openssl rand -hex 32)
docker compose up serve
```

## `serve` refuses to start without a token — on purpose

`docker compose config` **fails** when `GFLOW_CLI_DAEMON_TOKEN` is unset:

```
required variable GFLOW_CLI_DAEMON_TOKEN is missing a value: set a token before exposing this
```

That is the intended behaviour, not a bug to fix. Since v0.75.0 `gflow serve` verifies the token
on **every** request; a daemon exposed without one hands every tool to any local caller. The port
is published to `127.0.0.1` only for the same reason.

## Verified on this image

CI's matrix is `["3.11","3.12","3.13"]`, so the 3.14 base is not covered by the test suite.
A container pins its interpreter, so this is deterministic rather than an ambient version that
could surprise someone — and the gap is closed by verifying the image's runtime contract directly
rather than by staying on an older interpreter:

```
python           : 3.14.7
gflow_cli        : 0.75.0
chrome channel   : True          (is_playwright_chrome_channel_available)
chrome available : True          (is_chrome_available)
initialize       : OK, server "gflow-cli"
tools/list       : OK, 15 tools
```

Re-run that after any base-image bump. If it stops holding, the interpreter is the first suspect.

## Benchmark — measured 2026-09-15

Reproduce with `docker/Dockerfile.test` (copy `dockerignore.example` to `.dockerignore` at the
repo root first). All figures from this machine; treat them as shape, not as a spec.

| Metric | Result |
|---|---|
| Runtime image (real Chrome + Xvfb) | **1.65 GB** |
| Test image (repo + dev deps, no Chrome) | **714 MB** |
| Cold container -> `gflow --version` | **1475 / 1516 / 1511 ms** |
| Cold container -> MCP `initialize` + `tools/list` | **2228 / 2406 / 2495 ms** |
| `uv sync` during build | **14.8 s** |
| gflow's offline suite, **on Python 3.14** | **4379 passed, 28 skipped** in **6m08s** |

The MCP figure is the one that matters for agents: roughly **2.3 s from cold container to a usable
tool list**. A long-lived `serve` pays that once; a one-shot `docker run` pays it every call.

**The suite result is the point of the 3.14 base.** CI's matrix is `["3.11","3.12","3.13"]`, so
this is the first time gflow's tests have run on 3.14 at all — which is what makes the interpreter
choice a measurement rather than a preference.

### Two tests cannot pass in a container built from a git WORKTREE

`test_real_tree_passes_root_doc_check` and `test_the_generator_ships_only_what_git_tracks` both
shell out to `git ls-files` to introspect **the repository**. In a worktree, `.git` is a 71-byte
*pointer file*:

```
gitdir: C:/development/github/gflow-cli/.git/worktrees/container-spike
```

Docker copies the pointer faithfully, and inside the container it dangles:

```
fatal: not a git repository: /app/C:/development/github/gflow-cli/.git/worktrees/container-spike
```

Both then fail with `CalledProcessError … exit status 128`. **This is the build context, not the
interpreter** — they test repo state, not runtime behaviour. Build from the main checkout (where
`.git` is a real directory) and they have a repo to query. Adding `.git` to the context does *not*
fix it on its own; that was tried and the failures were identical.

## What is verified, and what is not

| | |
|---|---|
| `gflow` runs in the container | ✅ measured — `gflow, version 0.75.0` |
| Real Chrome at gflow's required path | ✅ measured — all three detectors return True |
| Headed Chrome launches and browses | ✅ measured — Chrome 153, real page title |
| No automation markers | ✅ measured — `navigator.webdriver` is `None` |
| One-time Google sign-in in a container | ❌ **not run** |
| Flow accepts the session; generation works | ❌ **not run** — a clean fingerprint is necessary, not sufficient |
| Windows profile mounted into Linux | ❌ **not run** — expected to fail on DPAPI cookie decryption, which would be a portability limit, not anti-automation |

If you run the sign-in arm, please report what happened on
[#822](https://github.com/ffroliva/gflow-cli/issues/822) either way. A failure is as useful as a
success, provided it names what it observed.
