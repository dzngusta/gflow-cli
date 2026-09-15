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
| `GET flow.google.com/` | 200, 152 716 B | 200, 152 689 B | **no** — 27 B, identical markers, same final URL |
| `GET flow.google.com/tools/flow` | 200, 152 757 B | 200, 152 712 B | **no** — 45 B, identical markers, same final URL |
| `POST …/data/batchexecute?rpcids=jwpduf` (no `at`) | **401**, 137 B | **401**, 137 B | **no** — byte-identical |
| `GET labs.google/fx/api/auth/session` | 200, 691 B, 1 email | 200, **2 B** (`{}`) | yes — but see below |

Marker sweep on the migrated host, both arms identical: `SNlM0e` **absent**,
XSRF-shaped token **absent**, `gaia_shaped_id` **absent**, any email **absent**
(`email_count` 0), `WIZ_global_data` present, `aisandbox-root` present,
`signin_cta` **present in both**.

Then the rendered DOM, same page, Tier-1 structural anchors only:

| Rendered anchor | authenticated | anonymous |
|---|---|---|
| `a[href*="SignOutOptions"]` | **1** | **0** |
| `a[href*="accounts.google.com/ServiceLogin\|/signin"]` | **0** | **1** |
| `[data-gaiaid], [data-authuser]` | 0 | 0 |
| custom elements (`flow-*`, `aisandbox*`) | 10 | 19 |
| settled URL | `flow.google.com/` | `flow.google.com/about` |

## Verdict, against the readings pre-registered before the run

**Q1 — `BROWSERLESS_BATCHEXECUTE_DEAD`.** No `SNlM0e` and no XSRF-shaped token in either
arm, on either migrated-host page. This re-confirms the 2026-09-12 re-measurement and
retires the 2026-09-03 finding for good.

**Q2 / Q2b — `NO_BROWSERLESS_ORACLE`.** Every migrated-host probe answered *identically*
in both arms. The batchexecute read is the sharp one: carrying a **valid session** and no
`at` token it returns **401**, and so does the anonymous arm — **the same status at the same 137
bytes**. `at` is therefore required for reads, it is no longer obtainable without a
browser, and the 401 reports *the missing token*, not the session state. It cannot be an
oracle.

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

**Q4 — `ORACLE_EXISTS_BUT_COSTS_A_BROWSER`.** The rendered DOM separates the arms cleanly,
on two independent Tier-1 anchors pointing the same way. This retires the "unverified"
label the predict verdict put on that instrument.

The contrast with the body sweep is the whole finding: **`signin_cta` is present in the raw
HTML of both arms, and in the rendered DOM of only the anonymous one.** Angular ships one
shell to everybody and decides after it boots. Any oracle that greps the response body is
reading the shell, not the session — which is why every browserless instrument above came
back flat.

**Q5 — `SERVER_ATTESTED_CONFIRMED`.** Added after council D3 on PR #835 pointed out that
Q4's control was **confounded**: its anonymous arm used a throwaway profile with no service
worker and an empty cache, while its authenticated arm was warm. So `signin_cta=1` there
was equally explained by "there was nothing cached to serve", and the case that actually
matters — *warm profile, caches intact, session dead* — had never been rendered. That is
exactly what a revoked session looks like from disk.

Re-run with `--warm-control`: copy the real profile, delete **only** the cookie jar, leave
everything else alone. `Cache`, `Code Cache` and `Service Worker` all confirmed present in
the copy. Result:

| arm | `signout_link` | `signin_cta` | settled URL |
|---|---|---|---|
| warm + no cookies, `service_workers=block` (what ships) | **0** | **1** | `/about` |
| warm + no cookies, `service_workers=allow` | **0** | **1** | `/about` |

Both arms render the landing page — `flow-landing-hero`, `flow-landing-pricing`,
`flow-landing-faq` — not the app. **A warm cache does not mask a dead session**, so the
rendered DOM is genuinely server-attested and cookie presence never decides. The two
service-worker arms are identical, which means the `service_workers="block"` the fix now
passes is belt-and-braces rather than load-bearing; it stays because it costs nothing and
removes a whole class of future doubt, not because it was observed to matter.

---

# ⛔ Q6 — RETRACTION: the rendered DOM is NOT server-attested, and this oracle does not work

**Added 2026-09-16, after the e2e went red. Everything below this line about "(a) is
satisfiable" is WRONG. Read this section before acting on any of it.**

At ~00:05 `profile_ffroliva` rendered `signout_link=1, signin_cta=0` at `/`. At ~01:05 the
same profile rendered `signout_link=0, signin_cta=1` at `/about` — with the flow.google.com
cookies still on disk and labs still returning a 691-byte authenticated session with an
email. `denon82` and `promo-denon82` render the same anonymous shape. Headed and headless,
stealth flags on and off: **identical in all four arms.** So it is not bot detection and it
is not headless.

It is the **`/about` redirect** — a known, account-scoped, already-measured phenomenon in
this repo ([#756](https://github.com/ffroliva/gflow-cli/issues/756),
[`2026-09-11-about-redirect-is-decided-client-side.md`](2026-09-11-about-redirect-is-decided-client-side.md)),
which I did not read before designing around it. That spike settles the mechanism:

- The hop is **client-side**, 192 ms after the app's own first navigation commits. No 3xx
  anywhere; the document resolves to `/project/<id>`, not `/about`.
- The failing arm's **only** request to `flow.google.com` is the document itself. **Zero
  `batchexecute`, zero of anything else.** Not "asked and was refused" — *never asked*.
- And decisively: *"`gflow project list` on `denon82` returns 50 projects **including** the
  one that redirects. The backend grants access while the frontend declines to open it."*

**Therefore the rendered DOM cannot attest to the session.** The app decides what to render
without consulting the server about auth at all. `signout_link == 0` means "this account is
in the `/about` state", which is **not** the same as "this session is dead" — the two are
routinely different, and #756 exists because of it.

## What that does to the claims above

| Claim | Status |
|---|---|
| Q1 / Q2 / Q2b — no browserless oracle; batchexecute 401 with a valid session; `SNlM0e` gone; no identity on the host | **stands** — plain HTTP measurements, unaffected |
| Q4 — "the rendered DOM separates the arms" | stands as a *correlation*, on one account, for one hour |
| Q4's mechanism — "server-attested, so it sees revocation" | **REFUTED.** An inference I made from that correlation. #756 measured the mechanism and it is client-side |
| Q5 — warm control "proves server-attested" | **REFUTED as proof.** A cookie-less copy rendering anonymous is equally explained by the client deciding anonymous. It never demonstrated attestation |
| "(a) is satisfiable" | **false** |

**Consequence: the fix built on this does not ship.** A probe reading `signout_link` would
report a perfectly authenticated user as logged out whenever their account is in the
`/about` state — locking them out of gflow exactly as #791 does. That is the failure this
work exists to remove, reintroduced by the remedy.

## What I got wrong, as method

Rung 1 of the spike ladder is *"read an existing capture — `docs/superpowers/spikes/` may
already hold the answer. Free."* Two spikes named `about-redirect` were sitting in that
directory. I went straight to writing a new probe, measured a real correlation, and then
asserted a **mechanism** the data never showed — the exact move the spike skill warns
against. The council did not catch it either; the e2e did, by going red on a live account
whose state changed underneath it.

## What would settle a replacement

Any candidate oracle must be checked against an account **in the `/about` state** before
it is believed, because that state is common here and silently mimics "logged out". The
one signal known to survive it is the backend: `gflow project list` returns projects on a
redirecting account. A **`batchexecute` read is therefore the lead worth pursuing** — but
Q2b showed it needs an `at` token that is no longer browserlessly obtainable, so it would
have to be issued from inside a booted app page rather than over plain HTTP.

---

## What this means for the design

> ⚠️ **Superseded by Q6 above.** Kept for the record, not as guidance.

**Conditions (a) and (b) cannot both be met today**, and Q4 says which one survives:

- **(a) is satisfiable** — the rendered DOM is genuinely server-attested. The app only
  renders a sign-out link when the server answered the bootstrap as an authenticated
  session, so it sees revocation, which cookie presence never can.
- **(b) is not** — it costs a browser launch.

So the shape that the evidence supports is **cookie-gate → browser probe**: derive
`flow_host_session` from the jar both readers already hold (cheap, no launch), and let it
*gate* a rendered-DOM probe that only runs on the narrow path — outcome in
`{GOOGLE_SESSION_ONLY, VERIFICATION_ERROR}` **and** flow.google.com cookies present. Every
ordinary verification still pays nothing; only the migrated-and-labs-dead case pays for a
browser, which is the case that is currently broken outright.

That keeps the predict verdict's intent — cookie presence gates, it does not decide — and
drops only the clause the surface no longer supports. **Amending it is a maintainer
decision and it gates Phase 3 for #791.**

## Not measured

- **A labs-dead account.** This profile is migrated with labs *alive*; the arms here are
  cookies-vs-no-cookies, not labs-alive-vs-labs-dead. What is measured — what
  flow.google.com discloses, and to whom — is the same question either way, but the
  end-to-end happy path still needs the #791 cohort to verify it. Named external blocker,
  per the Iron Law.
- **Locale.** Both arms ran on an `en` UI. The anchors are `href` substrings and so should
  be locale-invariant by construction, but `ru` is where #791 and #799 both live and it is
  unverified there.
- **Other read rpcids.** Only `jwpduf` was probed. `as29s` and the project-load reads may
  gate differently, though a shared `at` requirement makes that unlikely.
- **batchexecute *with* a valid `at`.** Not obtainable browserlessly, which is the finding.
- **Whether the 10-vs-19 custom-element delta is stable.** It points the same way as the
  two anchors, but one observation is not a signal, and it is not needed if the anchors hold.
