# flow.google.com has no browserless auth oracle — the #791 GO shape is unsatisfiable as written

**Date:** 2026-09-16 · **Issue:** [#791](https://github.com/ffroliva/gflow-cli/issues/791) ·
**Script:** [`scripts/dev/spike_migrated_session_oracle.py`](../../../scripts/dev/spike_migrated_session_oracle.py) ·
**Cost:** $0 (reads only) · **Profile:** `ffroliva` (served flow.google.com, labs session still alive)

## The question

`/gflow:predict` on #791 put two conditions on the migrated-host session oracle:

- **(a)** *"Cookie presence may **gate** a probe; it must not **be** one. It is blind to
  server-side revocation (password change, 'sign out of all devices'), which is the normal
  way a Google session dies."*
- **(b)** *"No second browser launch, no new module"* — the probe must run on the cookie jar
  `verify_flow_profile` already holds.

Together they demand a **server-attested signal reachable over plain HTTP**. Two prior
measurements disagreed about whether one still exists, and nothing in the tree settled it.

## What was measured

Two arms — the real cookie jar vs no cookies at all — against the same four probes.

| Probe | authenticated | anonymous | separates? |
|---|---|---|---|
| `GET flow.google.com/` | 200, 152 719 B | 200, 152 680 B | **no** — 39 B, identical markers, same final URL |
| `GET flow.google.com/tools/flow` | 200, 152 758 B | 200, 152 711 B | **no** — 47 B, identical markers, same final URL |
| `POST …/data/batchexecute?rpcids=jwpduf` (no `at`) | **401**, 140 B | **401**, 138 B | **no** |
| `GET labs.google/fx/api/auth/session` | 200, 691 B, 1 email | 200, **2 B** (`{}`) | yes — but see below |

Marker sweep on the migrated host, both arms identical: `SNlM0e` **absent**,
XSRF-shaped token **absent**, `gaia_shaped_id` **absent**, any email **absent**
(`email_count` 0), `WIZ_global_data` present, `aisandbox-root` present,
`signin_cta` **present in both**.

## Verdict, against the readings pre-registered before the run

**Q1 — `BROWSERLESS_BATCHEXECUTE_DEAD`.** No `SNlM0e` and no XSRF-shaped token in either
arm, on either migrated-host page. This re-confirms the 2026-09-12 re-measurement and
retires the 2026-09-03 finding for good.

**Q2 / Q2b — `NO_BROWSERLESS_ORACLE`.** Every migrated-host probe answered *identically*
in both arms. The batchexecute read is the sharp one: carrying a **valid session** and no
`at` token it returns **401**, and so does the anonymous arm, two bytes apart. `at` is
therefore required for reads, it is no longer obtainable without a browser, and the 401
reports *the missing token*, not the session state. It cannot be an oracle.

**Q3 — `IDENTITY_ABSENT`.** No email and no GAIA-shaped id anywhere on the migrated host,
in either arm. `user_email` must be `None` on the migrated arm — exactly as the predict
verdict anticipated, so the `assert` at `real_chrome.py:458` has to soften.

### The one probe that *does* separate the arms is the one that cannot help

`labs.google/fx/api/auth/session` splits cleanly — 691 B with the account email, versus a
2-byte `{}`. That is the **oracle gflow already has**, and it is precisely the endpoint
that is dead for the #791 cohort. Reading "server-attested oracle found" off that row is
the mistake this spike's own first verdict function made, and it is the same defect as
[#743](https://github.com/ffroliva/gflow-cli/issues/743): a verdict computed over an
incomplete set. The verdict function now scopes Q2/Q3 to the migrated host.

## What this means for the design

**Conditions (a) and (b) cannot both be met today.** There is no server-attested signal on
flow.google.com reachable over plain HTTP. So the choice is forced:

- keep **(a)** and spend a browser on a rendered-DOM probe — the instrument at
  `2026-09-06-labs-vs-migrated-session-credential.md:94-99` (`avatar > 0` /
  `signin_cta == 0`), still unverified, and note that `signin_cta` is present in the raw
  HTML of *both* arms, so it must be read from the **rendered** DOM, never the body; or
- keep **(b)** and accept that cookie presence is the whole oracle — which the predict
  verdict already rejected, and which would report `AUTHENTICATED` for a revoked session.

**The verdict is what needs amending, not the code.** That is a maintainer decision, and
it is the gate on Phase 3 for #791.

## Not measured

- **The rendered-DOM instrument itself.** This spike made no browser probe; whether
  `avatar` / `signin_cta` separate the arms in the *rendered* Angular DOM is still open,
  and it is the obvious next rung.
- **Other read rpcids.** Only `jwpduf` was probed. `as29s` and the project-load reads may
  gate differently, though a shared `at` requirement makes that unlikely.
- **batchexecute *with* a valid `at`.** Not obtainable browserlessly, which is the finding.
- **The #791 cohort itself.** This profile is migrated with labs *alive*. The arms here are
  cookies-vs-no-cookies, not labs-alive-vs-labs-dead. Nothing measured here is evidence
  about what a labs-dead account is served — only about what flow.google.com discloses
  over plain HTTP, which is the same question either way.
