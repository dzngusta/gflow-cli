"""Spike: does flow.google.com still expose a server-attested auth signal that is
readable WITHOUT a browser? (#791 — migrated-host session oracle)

COST: $0. Reads only — GET on bootstrap/session endpoints. No generation, no
entity creation, nothing to clean up afterwards.

WHY THIS EXISTS
---------------
`/gflow:predict` on #791 (issue comment 2026-09-12) set two conditions on the
migrated-host oracle that are in tension, and nothing in the tree settles them:

  (a) "Cookie presence may GATE a probe; it must not BE one. It is blind to
      server-side revocation (password change, 'sign out of all devices'),
      which is the normal way a Google session dies."
  (b) "No second browser launch, no new module" — the probe must run on the
      cookie jar `verify_flow_profile` already holds.

Together those demand a server-attested signal reachable over plain HTTP.
Two prior measurements disagree about whether one still exists:

  2026-09-03  browserless batchexecute PROVEN — `SNlM0e` scraped from the
              bootstrap body (42 chars), 3 read RPCs -> HTTP 200, cookies only.
              (memory: flow-google-com-batchexecute-headless-proven)
  2026-09-12  re-measured on the same profile with anonymous controls —
              `SNlM0e` ABSENT, account email absent in EVERY arm, the
              authenticated<->anonymous delta just 45 bytes of nonce noise.
              (memory: flow-google-com-body-no-longer-carries-identity)

The later measurement retired the identity block. It did NOT re-test whether
some *other* response field still separates the two arms. That gap is what
blocks the design, so it is what this spike measures.

PRE-REGISTERED READINGS — written before the run; do not reinterpret after
--------------------------------------------------------------------------
Q1. Is `SNlM0e` (or any XSRF-shaped bootstrap token) present?
    present in A only  -> the token is ITSELF an auth signal; browserless
                          batchexecute is viable and this is the probe.
    present in A and B -> token available but carries no signal; go to Q2.
    absent in both     -> browserless batchexecute is DEAD. A batchexecute
                          probe cannot satisfy condition (b), and the oracle
                          needs a browser.

Q2. Does any endpoint answer differently for A (cookies) than B (anonymous)?
    status, final URL, or a structural body marker differs
                       -> server-attested browserless oracle FOUND; name it.
    every arm identical -> no browserless server-attested oracle on this host
                          today. Cookie presence would have to gate a
                          *rendered-DOM* probe, which needs a browser — so
                          condition (b) as written is unsatisfiable and the
                          predict verdict needs amending, not the code.

Q2b. (added before the second run, after Q1 came back "absent in both")
    Does a READ batchexecute RPC gate on cookies alone, with no `at` token?
    arms differ on status / envelope / wrb frame
                       -> browserless server-attested oracle FOUND even though
                          the XSRF token is gone; `at` was never required for
                          reads, and this is the probe.
    arms identical     -> confirms Q2. No browserless oracle on this host; the
                          predict verdict's "no second browser launch" is
                          unsatisfiable together with "must be server-attested",
                          and the verdict is what has to change.

Q4. (added before the third run, after Q2/Q2b came back "no browserless oracle")
    Does the RENDERED DOM separate the arms? This is the instrument the predict
    verdict listed as "what may still work (unverified)" — from spike
    2026-09-06-labs-vs-migrated-session-credential.md:94-99.
    arms differ on a Tier-1 structural anchor
                       -> the oracle EXISTS but costs a browser. Condition (a)
                          is satisfiable, (b) is not, and the design is
                          cookie-gate -> browser probe on the narrow path.
    arms identical     -> NOTHING on flow.google.com separates an authenticated
                          client from an anonymous one, by any instrument we
                          have. The oracle concept collapses and #791 needs a
                          different approach entirely — report that loudly.

Q3. Does any arm carry the account email or a GAIA-shaped id?
    present -> `user_email` can be populated on the migrated arm.
    absent  -> `user_email` must be None, and the assert at
               real_chrome.py:458 has to soften. (predict already expects this)

A 0/N result on every instrument is NOT evidence that the condition is
transient. It is UNMEASURED, and unmeasured is the finding to report.

USAGE
-----
    python scripts/dev/spike_migrated_session_oracle.py --profile ffroliva
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, cast

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

from gflow_cli.config import get_settings  # noqa: E402
from gflow_cli.profile_lease import ProfileLease  # noqa: E402

# Endpoints probed in BOTH arms. All read-only, all free.
_PROBES = (
    ("flow_root", "https://flow.google.com/"),
    ("flow_tools", "https://flow.google.com/tools/flow"),
    ("labs_session", "https://labs.google/fx/api/auth/session"),
)

# Structural markers hunted for in every body. Presence/absence is the datum —
# never the value, which would be a credential.
_MARKERS: dict[str, re.Pattern[str]] = {
    "SNlM0e": re.compile(r"SNlM0e"),
    "xsrf_shaped": re.compile(r'"(?:at|xsrf|xsrfToken)"\s*:\s*"[\w:-]{20,}"'),
    "wiz_global_data": re.compile(r"WIZ_global_data"),
    "gaia_shaped_id": re.compile(r"\b\d{21}\b"),
    "any_email": re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}"),
    "signin_cta": re.compile(r"accounts\.google\.com/(?:ServiceLogin|signin)"),
    "aisandbox_root": re.compile(r"aisandbox-root"),
}


def _cookie_header(jar: list[dict[str, Any]], host: str) -> str:
    """Build a Cookie header for `host` from the FULL jar.

    Deliberately not `ctx.cookies([url])` — that URL filter only returns
    cookies whose path matches "/", silently dropping path-scoped session
    tokens (see cookies.py and #222/#230).
    """
    parts: list[str] = []
    for c in jar:
        domain = str(c.get("domain", "")).lstrip(".")
        if not domain or not (host == domain or host.endswith("." + domain)):
            continue
        name, value = c.get("name"), c.get("value")
        if isinstance(name, str) and name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


async def _read_full_jar(profile_dir: Path) -> list[dict[str, Any]]:
    """Read the complete cookie jar under the profile lease.

    Lease is mandatory: Chrome must never start on a profile this process does
    not own (spike SKILL.md § Profile etiquette). A ProfileLockedError here
    means another holder owns it — wait or pick another profile; never kill.
    """
    from playwright.async_api import async_playwright

    from gflow_cli.browser_manager import channel_for_profile, ensure_profile_engine_compatible

    channel = channel_for_profile(profile_dir)
    async with ProfileLease(profile_dir):
        ensure_profile_engine_compatible(profile_dir, channel)
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel=channel,
                headless=True,
                args=["--password-store=basic"],
            )
            try:
                return [dict(c) for c in await ctx.cookies()]
            finally:
                await ctx.close()


def _probe(url: str, cookie: str) -> dict[str, Any]:
    """One GET. Records status, redirect chain, size and marker presence."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookie:
        headers["Cookie"] = cookie
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            resp = client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001 — a failed arm is a datum, not a crash
        return {"error": type(exc).__name__, "detail": str(exc)[:200]}
    body = resp.text
    return {
        "status": resp.status_code,
        "final_url": str(resp.url),
        "redirected": str(resp.url) != url,
        "bytes": len(body),
        "markers": {name: bool(pat.search(body)) for name, pat in _MARKERS.items()},
        # Count only — a value here would be a credential in a shareable file.
        "email_count": len(set(_MARKERS["any_email"].findall(body))),
    }


def _batchexecute(cookie: str) -> dict[str, Any]:
    """POST a READ rpcid with NO `at` token — does batchexecute gate on cookies alone?

    `jwpduf` is a status/poll read (migrated_composer.STATUS_RPCS). The args are
    deliberately a throwaway id: a well-formed *argument* is not needed to learn
    whether the transport authenticates, and a read cannot spend anything.

    What matters is only whether the two arms answer differently. If they do,
    that difference IS the browserless server-attested oracle the predict
    verdict asked for.
    """
    url = (
        "https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute"
        "?rpcids=jwpduf&rt=c&_reqid=1"
    )
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
    }
    if cookie:
        headers["Cookie"] = cookie
    payload = {"f.req": '[[["jwpduf","[\\"spike-probe\\"]",null,"generic"]]]'}
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            resp = client.post(url, headers=headers, data=payload)
    except Exception as exc:  # noqa: BLE001 — a failed arm is a datum
        return {"error": type(exc).__name__, "detail": str(exc)[:200]}
    body = resp.text
    return {
        "status": resp.status_code,
        "final_url": str(resp.url),
        "bytes": len(body),
        # Shape only — never the payload, which can carry account data.
        "has_envelope": body.startswith(")]}'"),
        "has_wrb_frame": "wrb.fr" in body,
        "looks_like_signin": "accounts.google.com" in body[:4000],
    }


async def _rendered_dom(profile_dir: Path | None) -> dict[str, Any]:
    """Rendered-DOM probe on flow.google.com — `profile_dir=None` is the anonymous control.

    Tier-1 structural anchors only (AGENTS.md locale-invariance): `href`
    substrings and custom-element tag names. Never display text — the raw HTML
    already showed `signin_cta` present in BOTH arms, so any text or link-in-
    source heuristic is known-wrong here; only what Angular actually renders
    can carry the signal.

    `goto` returns before Flow's client-side redirect settles (memory:
    goto-returns-before-client-side-redirect), so this waits for the network to
    go idle before snapshotting.
    """
    from playwright.async_api import async_playwright

    from gflow_cli.browser_manager import channel_for_profile, ensure_profile_engine_compatible

    js = """() => {
        const q = (s) => document.querySelectorAll(s).length;
        const tags = new Set(
            [...document.querySelectorAll('*')]
                .map(e => e.tagName.toLowerCase())
                .filter(t => t.startsWith('flow-') || t.startsWith('aisandbox'))
        );
        return {
            signout_link: q('a[href*="SignOutOptions"]'),
            account_link: q('a[href*="myaccount.google.com"]'),
            signin_cta: q('a[href*="accounts.google.com/ServiceLogin"], '
                        + 'a[href*="accounts.google.com/signin"]'),
            gaiaid_attr: q('[data-gaiaid], [data-authuser]'),
            aisandbox_root: q('aisandbox-root'),
            custom_elements: [...tags].sort(),
            url: location.href,
        };
    }"""

    async with AsyncExitStack() as stack:
        # Chrome must never start on a profile this process does not own.
        if profile_dir is not None:
            await stack.enter_async_context(ProfileLease(profile_dir))
        pw = await stack.enter_async_context(async_playwright())
        if profile_dir is not None:
            channel = channel_for_profile(profile_dir)
            ensure_profile_engine_compatible(profile_dir, channel)
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel=channel,
                headless=True,
                args=["--password-store=basic"],
            )
        else:
            import tempfile

            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=tempfile.mkdtemp(prefix="spike_anon_"),
                headless=True,
                args=["--password-store=basic"],
            )
        try:
            page = await ctx.new_page()
            await page.goto("https://flow.google.com/", wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:  # noqa: BLE001 — a busy page is still snapshottable
                await page.wait_for_timeout(5_000)
            return cast("dict[str, Any]", await page.evaluate(js))
        finally:
            await ctx.close()


def _verdict(result: dict[str, Any]) -> dict[str, str]:
    """Apply the pre-registered readings to the data. No freehand grading.

    Scoped to the MIGRATED HOST on purpose. `labs_session` is the oracle we
    already have and the one that is dead for the #791 cohort — letting it
    into Q2/Q3 reports "oracle found" from the very endpoint that cannot serve
    them. (Same defect as #743: a verdict computed over an incomplete set.)
    """
    out: dict[str, str] = {}
    arms = result["arms"]
    migrated = [name for name, url in _PROBES if "flow.google.com" in url]

    def marker(arm: str, probe: str, name: str) -> bool:
        return bool(arms[arm].get(probe, {}).get("markers", {}).get(name))

    tok = {
        arm: any(marker(arm, p, m) for p in migrated for m in ("SNlM0e", "xsrf_shaped"))
        for arm in ("authenticated", "anonymous")
    }
    if tok["authenticated"] and not tok["anonymous"]:
        out["Q1"] = "TOKEN_IS_A_SIGNAL — present authenticated-only; browserless probe viable"
    elif tok["authenticated"]:
        out["Q1"] = "TOKEN_PRESENT_NO_SIGNAL — available in both arms; see Q2"
    else:
        out["Q1"] = "BROWSERLESS_BATCHEXECUTE_DEAD — no XSRF token on the migrated host"

    differing = [
        name
        for name in migrated
        if any(
            arms["authenticated"].get(name, {}).get(k) != arms["anonymous"].get(name, {}).get(k)
            for k in ("status", "final_url", "markers")
        )
    ]
    bx_a, bx_b = (
        arms["authenticated"].get("batchexecute", {}),
        arms["anonymous"].get("batchexecute", {}),
    )
    if any(bx_a.get(k) != bx_b.get(k) for k in ("status", "has_envelope", "has_wrb_frame")):
        differing.append("batchexecute")
    out["Q2"] = (
        f"SERVER_ATTESTED_ORACLE_FOUND — migrated-host arms differ on: {', '.join(differing)}"
        if differing
        else "NO_BROWSERLESS_ORACLE — every migrated-host probe answered identically in both arms"
    )

    id_a = any(marker("authenticated", p, m) for p in migrated for m in ("gaia_shaped_id",))
    emails = any(arms["authenticated"].get(p, {}).get("email_count", 0) for p in migrated)
    out["Q3"] = (
        "IDENTITY_PRESENT — user_email may be populatable from the migrated host"
        if (id_a or emails)
        else "IDENTITY_ABSENT — user_email must be None on the migrated arm"
    )

    dom_a = arms["authenticated"].get("rendered_dom", {})
    dom_b = arms["anonymous"].get("rendered_dom", {})
    anchors = ("signout_link", "account_link", "signin_cta", "gaiaid_attr")
    dom_diff = [k for k in anchors if dom_a.get(k) != dom_b.get(k)]
    if dom_diff:
        out["Q4"] = (
            f"ORACLE_EXISTS_BUT_COSTS_A_BROWSER — rendered DOM differs on: {', '.join(dom_diff)}"
        )
    elif dom_a and dom_b:
        out["Q4"] = "NO_ORACLE_BY_ANY_INSTRUMENT — rendered DOM identical too; concept collapses"
    else:
        out["Q4"] = "UNMEASURED — a rendered-DOM arm did not complete"
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="ffroliva", help="profile name under GFLOW_CLI_HOME")
    args = ap.parse_args()

    profile_dir = get_settings().home / f"profile_{args.profile}"
    if not profile_dir.is_dir():
        print(f"no such profile: {profile_dir}", file=sys.stderr)
        return 2

    print(f"[1/3] reading full cookie jar from {profile_dir.name} (under lease)...")
    jar = await _read_full_jar(profile_dir)
    hosts = {str(c.get("domain", "")).lstrip(".") for c in jar}
    print(f"      {len(jar)} cookies across {len(hosts)} domains")

    result: dict[str, Any] = {
        "profile": args.profile,
        "jar": {
            "total": len(jar),
            "flow_google_com": sum(1 for c in jar if "flow.google.com" in str(c.get("domain", ""))),
            "labs_google": sum(1 for c in jar if "labs.google" in str(c.get("domain", ""))),
            "has_SAPISID": any(c.get("name") == "SAPISID" for c in jar),
            "has_flow_osid": any(
                c.get("name") in ("__Secure-OSID", "OSID")
                and "flow.google.com" in str(c.get("domain", ""))
                for c in jar
            ),
        },
        "arms": {"authenticated": {}, "anonymous": {}},
    }

    for arm in ("authenticated", "anonymous"):
        print(f"[2/3] arm: {arm}")
        for name, url in _PROBES:
            host = httpx.URL(url).host
            cookie = _cookie_header(jar, host) if arm == "authenticated" else ""
            result["arms"][arm][name] = _probe(url, cookie)
            node = result["arms"][arm][name]
            print(f"      {name}: {node.get('status', node.get('error'))} {node.get('bytes', '')}b")
        bx_cookie = _cookie_header(jar, "flow.google.com") if arm == "authenticated" else ""
        result["arms"][arm]["batchexecute"] = _batchexecute(bx_cookie)
        bx = result["arms"][arm]["batchexecute"]
        print(
            f"      batchexecute(jwpduf, no `at`): {bx.get('status', bx.get('error'))} "
            f"{bx.get('bytes', '')}b envelope={bx.get('has_envelope')} "
            f"wrb={bx.get('has_wrb_frame')}"
        )

    for arm, target in (("authenticated", profile_dir), ("anonymous", None)):
        print(f"[3/4] rendered DOM: {arm}")
        try:
            dom = await _rendered_dom(target)
        except Exception as exc:  # noqa: BLE001 — a failed arm is a datum, not a crash
            dom = {"error": type(exc).__name__, "detail": str(exc)[:200]}
        result["arms"][arm]["rendered_dom"] = dom
        print(
            f"      signout={dom.get('signout_link')} account={dom.get('account_link')} "
            f"signin_cta={dom.get('signin_cta')} gaiaid={dom.get('gaiaid_attr')} "
            f"custom={len(dom.get('custom_elements', []))}"
        )

    result["verdict"] = _verdict(result)

    out_dir = _ROOT / "scripts" / "dev" / "_spike_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"spike_migrated_session_oracle_{args.profile}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("[4/4] verdict (pre-registered readings applied):")
    for q, v in result["verdict"].items():
        print(f"      {q}: {v}")
    print(f"      evidence -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
