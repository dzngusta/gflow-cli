# Credits on flow.google.com: the price is on screen before submit; the balance was not found

**Date:** 2026-09-14 · **Cost:** $0 (navigation, DOM reads, a typed-and-cleared prompt, opening
the settings pane; nothing submitted, created or deleted) · **Issues:** #795 (Refs #639) ·
**Script:** `scripts/dev/spike_credits_migrated_surface.py` (readings pre-registered in its
docstring, committed before each run: `f0cfcd55` for v1, `9e038489` for v2)

**Question.** Can gflow read per-model credit prices and the credit balance on an account served
`flow.google.com`, without spending anything? It decides whether a spend cap
(community-feedback-uplift WS2) can be built on this host now or is blocked on #795.

## What was observed

| Run | Profile | Host served | Result |
|---|---|---|---|
| v1 | `denon82` | `flow.google.com/about` (marketing page) | **UNMEASURED** — no app, no project grid |
| v1 | `ci-probe` | `flow.google.com/project/<id>` | No credit text in the page before or after typing; the only credit-shaped wire hit was `cPZSdc`, a promotional banner |
| v2 | `ci-probe` | `flow.google.com/project/<id>` | Settings pane: **"Generating will use 0 credits"** with Image · Nano Banana 2 Lite · x1 selected |

**1. The declared price is readable from the composer's settings pane before submit.** Opening
gflow's own anchor `.settings-trigger-button` (`migrated_composer.READY_ANCHOR`) shows a pane whose
last line pairs a number with credits and follows the current mode, model and count. With an image
model at x1 it read **0** — images spend daily quota, not credits. For video the same line read
**12** for Omni 1.1 Flash · 720p · 8 s · x1 in
[2026-09-05-migrated-host-wire-protocol](2026-09-05-migrated-host-wire-protocol.md); the video
value was not re-measured today.

**2. No price was found on the wire.** `HTrJv` (≈25 KB, on project load) is a model catalog mapping
ids to display names (`veo_3_1_t2v_fast_4s_relaxed` → "Veo 3.1 - Fast"); the model tokens in it
were not next to price-like integers. `tRARke` (≈32 KB) is the community tools gallery. Payloads are
positional arrays, so a bare number carries no key; only the snippets around model tokens were read,
not every integer in every body.

**3. No balance was found.** No page text, no aria-label and no watched response carried a
balance on either profile. `fetch_credits_http` returned `AisandboxAuthError: credits endpoint
returned 401` on both profiles.

## What this means for WS2

- A cap on **declared price** is buildable on this host now: the migrated composer already opens
  the settings pane to choose model and count, so reading the cost line there adds no navigation.
  It needs a **structural anchor** for that line (it was located by its text in this spike, which
  is discovery only — never a production selector) and a locale-independent number parse.
- A cap that compares against the **balance** is not buildable on this host yet — the balance
  surface is still unlocated (#795). Flow's own shortfall warning (`prompt-warning-button`) is
  already mapped to `InsufficientCreditsError`, so a user cannot silently overspend the balance.
- The labs route (`projectInitialData` `creditMapping` + `remainingCredits`) cannot be used on
  these profiles.

## Not measured

- The video cost line today, for each video model and for counts above x1.
- Whether the cost line updates without reopening the pane after changing count.
- Every integer in `HTrJv`, `Zzl0ze`, `UpteDb` and `o30O0e` bodies — a price or balance could be
  positional there; only model-token neighbourhoods were read.
- Any traffic after submit (deliberately excluded: costs credits).
- `denon82` beyond `/about` (see the 2026-09-10 `/about` redirect spikes).

**What would settle the balance question:** the HAR harness with a human opening Flow's account or
plan surface on a `flow.google.com` profile, then searching the capture for the balance the UI shows.
