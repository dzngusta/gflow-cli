"""Flow app-session verification — the single source of truth for
"is this profile signed in to the Flow app?".

A profile can hold Google SSO cookies (e.g. SAPISID) without holding the Flow
app's NextAuth session (`__Secure-next-auth.session-token`). Only the latter
authenticates Flow's tRPC API. This module probes the same surface
`FlowApiClient` authenticates on — the NextAuth session endpoint — so a login
is never reported successful unless a real, usable Flow session exists.

See docs/superpowers/specs/2026-05-17-issue-15-auth-verification-fix-design.md
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import structlog

from gflow_cli.config import get_settings
from gflow_cli.errors import SecurityError
from gflow_cli.profile_lease import ProfileLease

from .cookies import _has_flow_host_session, get_chrome_cookie_snapshot

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from playwright.async_api import BrowserContext

logger = structlog.get_logger(__name__)

# The NextAuth session endpoint. Expected authenticated 200 body shape:
#   {"user": {"name": ..., "email": ..., "image": ...}, "expires": "..."}
# An unauthenticated request returns `200 {}`. This contract is pinned by the
# AUTHENTICATED_BODY fixture in tests/auth/test_verification.py — if Google
# changes the shape, that test fails rather than the change going silent.
SESSION_API_URL = "https://labs.google/fx/api/auth/session"

# Per-request timeout for the session probe (milliseconds).
_REQUEST_TIMEOUT_MS = 15_000
# Total fetch attempts (initial + retries) before giving up.
_MAX_ATTEMPTS = 3
# HTTP statuses worth retrying — transient server-side conditions only.
_RETRYABLE_STATUSES = frozenset({429, 503, 504})
_SESSION_HEADERS = {
    "accept": "*/*",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "referer": "https://labs.google/fx/tools/flow",
}


class FlowSessionOutcome(StrEnum):
    """Mutually-exclusive results of probing a profile for a Flow session."""

    AUTHENTICATED = "authenticated"
    GOOGLE_SESSION_ONLY = "google_session_only"
    NO_SESSION = "no_session"
    VERIFICATION_ERROR = "verification_error"
    #: The profile's `.gflow_browser_strategy` marker is missing, so the
    #: Playwright cookie reader refuses to open it (#796). Distinct from
    #: VERIFICATION_ERROR because the cause is local profile state, not the
    #: network — and telling the user to "check connectivity" sends them
    #: looking in the wrong place, on a profile a failed login just rolled back.
    PROFILE_MARKER_MISSING = "profile_marker_missing"


_DETAIL_BY_OUTCOME: dict[FlowSessionOutcome, str] = {
    FlowSessionOutcome.AUTHENTICATED: "Flow app session verified.",
    FlowSessionOutcome.GOOGLE_SESSION_ONLY: "Signed in to Google, but not to the Flow app.",
    FlowSessionOutcome.NO_SESSION: "No sign-in detected.",
    FlowSessionOutcome.VERIFICATION_ERROR: "Could not verify the Flow session.",
    FlowSessionOutcome.PROFILE_MARKER_MISSING: (
        "This profile is missing its Chrome-strategy marker."
    ),
}


@dataclass(frozen=True)
class FlowSessionStatus:
    """The verdict of a Flow-session probe.

    `detail` is a derived property — always one of the fixed strings in
    `_DETAIL_BY_OUTCOME`, never built from response, cookie, or exception
    content. Deriving it (rather than storing a free string) makes it
    structurally impossible to leak a secret through this field.
    """

    outcome: FlowSessionOutcome
    user_email: str | None
    source: str  # caller-supplied log label ("chrome"/"internal"); never from response/cookie data
    flow_host_session: bool = False

    @property
    def detail(self) -> str:
        return _DETAIL_BY_OUTCOME[self.outcome]

    @property
    def authenticated(self) -> bool:
        return self.outcome is FlowSessionOutcome.AUTHENTICATED

    @property
    def migrated_probe_warranted(self) -> bool:
        """Whether to spend a browser confirming this against flow.google.com.

        Both halves matter. The outcome set is widened past GOOGLE_SESSION_ONLY
        to include VERIFICATION_ERROR deliberately: a dead labs endpoint is the
        very scenario the migrated probe exists for, and restricting to
        GOOGLE_SESSION_ONLY would switch the fallback off on the day it is
        finally needed.

        AUTHENTICATED never re-probes (labs already answered), and NO_SESSION
        never probes at all — no SAPISID means signed out of Google entirely,
        which no amount of browser can fix.
        """
        return self.flow_host_session and self.outcome in {
            FlowSessionOutcome.GOOGLE_SESSION_ONLY,
            FlowSessionOutcome.VERIFICATION_ERROR,
        }


def _validate_profile_in_home(profile_dir: Path) -> None:
    """Raise SecurityError when a profile escapes GFLOW_CLI_HOME."""
    home = get_settings().home.resolve()
    try:
        profile_dir.resolve(strict=True).relative_to(home)
    except (ValueError, OSError):
        msg = f"Profile directory {profile_dir} is outside of GFLOW_CLI_HOME ({home})."
        raise SecurityError(
            msg,
        ) from None


def evaluate_session_response(
    status_code: int,
    body: str,
    *,
    google_session: bool,
    source: str,
    flow_host_session: bool = False,
) -> FlowSessionStatus:
    """Map a raw /api/auth/session response to a FlowSessionStatus.

    Pure and total: no I/O, no exceptions raised or used for control flow.
    Every (status_code, body) maps to exactly one outcome. Fail-closed — only
    a 200 carrying a usable `user.email` yields AUTHENTICATED. Only `email` is
    read; `name`, `image`, and `expires` are ignored, and the parsed dict is
    never retained beyond this function.

    `flow_host_session` is carried through untouched — it never changes an
    outcome here. It only surfaces as `migrated_probe_warranted`, so that both
    oracle call sites gate the browser probe identically without duplicating
    the rule.
    """

    def _result(outcome: FlowSessionOutcome, email: str | None = None) -> FlowSessionStatus:
        return FlowSessionStatus(
            outcome=outcome,
            user_email=email,
            source=source,
            flow_host_session=flow_host_session,
        )

    if status_code != 200:
        return _result(FlowSessionOutcome.VERIFICATION_ERROR)

    try:
        parsed: Any = json.loads(body)
    except ValueError:
        # json.JSONDecodeError is a subclass of ValueError, so this catches both.
        return _result(FlowSessionOutcome.VERIFICATION_ERROR)

    if not isinstance(parsed, dict):
        return _result(FlowSessionOutcome.VERIFICATION_ERROR)

    parsed_dict = cast("dict[str, Any]", parsed)
    user = parsed_dict.get("user")
    if user is None or user == {}:
        # Authenticated-shaped endpoint reachable, but no Flow session.
        if google_session:
            return _result(FlowSessionOutcome.GOOGLE_SESSION_ONLY)
        return _result(FlowSessionOutcome.NO_SESSION)

    if not isinstance(user, dict):
        return _result(FlowSessionOutcome.VERIFICATION_ERROR)

    user_dict = cast("dict[str, Any]", user)
    email = user_dict.get("email")
    if isinstance(email, str) and email:
        return _result(FlowSessionOutcome.AUTHENTICATED, email)

    # `user` present but no usable email — unexpected shape (see spec §10).
    return _result(FlowSessionOutcome.VERIFICATION_ERROR)


async def _fetch_session(ctx: BrowserContext) -> tuple[int, str]:
    """Fetch /api/auth/session, retrying transient failures.

    Returns the final (status_code, body). Makes up to `_MAX_ATTEMPTS`
    attempts; an attempt is retried only on a network/timeout error or an
    HTTP status in `_RETRYABLE_STATUSES`, with exponential backoff (1s, 2s;
    capped at 8s). Re-raises the last error if no attempt produced a response.

    An explicit loop (rather than a `tenacity` decorator) is used so the final
    `(status_code, body)` survives — the caller logs the real status code as a
    durability signal (spec §10). The spec (§4.1) sanctions either form.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await ctx.request.get(SESSION_API_URL, timeout=_REQUEST_TIMEOUT_MS)
            body = await resp.text()
        # A network/timeout error is retried below, or re-raised on the final attempt.
        except Exception as exc:
            last_exc = exc
            if attempt == _MAX_ATTEMPTS:
                raise
        else:
            if resp.status not in _RETRYABLE_STATUSES or attempt == _MAX_ATTEMPTS:
                return resp.status, body
        await asyncio.sleep(float(min(2 ** (attempt - 1), 8)))
    # Unreachable — the loop always returns or raises by the final attempt.
    raise last_exc or RuntimeError("session probe produced no response")


async def _fetch_session_httpx(client: Any) -> tuple[int, str]:
    """Fetch /api/auth/session via httpx, retrying transient failures.

    Mirrors `_fetch_session` exactly — same attempt count, same retryable
    statuses, same exponential backoff — so the httpx fast path and the
    Playwright path have identical durability characteristics. A single
    transient 429/503/504 or network blip will not reject a valid login.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.get(SESSION_API_URL)
            status_code: int = resp.status_code
            body: str = resp.text
        except Exception as exc:
            last_exc = exc
            if attempt == _MAX_ATTEMPTS:
                raise
        else:
            if status_code not in _RETRYABLE_STATUSES or attempt == _MAX_ATTEMPTS:
                return status_code, body
        await asyncio.sleep(float(min(2 ** (attempt - 1), 8)))
    # Unreachable — the loop always returns or raises by the final attempt.
    raise last_exc or RuntimeError("session probe produced no response")


async def fetch_flow_session_httpx(
    profile_dir: Path,
) -> tuple[int, str, bool, bool]:
    """Read a profile's cookies and probe Flow's session endpoint with retries.

    The client created here is scoped to ``labs.google`` and is closed before
    the caller receives the response. Callers must use a separate client for
    any other host so Flow session cookies cannot cross an origin boundary.

    Returns ``(status_code, body, google_session, flow_host_session)``.
    """
    _validate_profile_in_home(profile_dir)

    import httpx

    cookie_snapshot = await get_chrome_cookie_snapshot(profile_dir)
    async with httpx.AsyncClient(
        cookies=cookie_snapshot.httpx_cookies,
        headers=_SESSION_HEADERS,
        follow_redirects=False,
        timeout=15.0,
    ) as client:
        status_code, body = await _fetch_session_httpx(client)
    return (
        status_code,
        body,
        cookie_snapshot.google_session,
        cookie_snapshot.flow_host_session,
    )


# Tier-1 structural anchors only — `href` substrings, never display text. The
# raw HTML carries a sign-in link in BOTH the authenticated and anonymous arms
# (measured), so only what Angular actually renders can decide. Locale-invariant
# by construction: these are URLs, not labels.
_MIGRATED_PROBE_URL = "https://flow.google.com/"
_MIGRATED_DOM_JS = """() => ({
    signout_link: document.querySelectorAll('a[href*="SignOutOptions"]').length,
    signin_cta: document.querySelectorAll(
        'a[href*="accounts.google.com/ServiceLogin"], a[href*="accounts.google.com/signin"]'
    ).length,
})"""


def evaluate_migrated_dom(counts: Mapping[str, int]) -> bool:
    """Read a rendered flow.google.com DOM as authenticated, or not.

    Pure. Requires the authenticated anchor present AND the anonymous anchor
    absent, so anything ambiguous fails closed:

    - neither anchor  -> the app had not finished booting. Not a verdict.
    - both anchors    -> contradictory (an account chooser can render both).

    Measured 2026-09-16 (spike 2026-09-16-migrated-session-oracle-needs-a-browser):
    authenticated signout_link=1 signin_cta=0; anonymous signout_link=0 signin_cta=1.
    """
    return counts.get("signout_link", 0) > 0 and counts.get("signin_cta", 0) == 0


async def read_migrated_dom(ctx: BrowserContext) -> Mapping[str, int]:
    """Count the anchors on flow.google.com in an ALREADY-OPEN context.

    Callers that hold a live browser — `verify_flow_session` and the
    `--browser internal` poll — use this and pay no extra launch.
    """
    page = await ctx.new_page()
    try:
        # `goto` returns before Flow's client-side redirect settles, so a
        # one-shot read here would sample the pre-boot shell and report
        # "neither anchor" for a perfectly good session.
        await page.goto(_MIGRATED_PROBE_URL, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:  # noqa: BLE001 — a busy page is still readable
            await page.wait_for_timeout(5_000)
        return cast("Mapping[str, int]", await page.evaluate(_MIGRATED_DOM_JS))
    finally:
        await page.close()


async def _render_migrated_dom(profile_dir: Path, channel: str | None) -> Mapping[str, int]:
    """Launch a headless context purely to read the migrated DOM.

    Only the httpx fast path needs this — it has no browser of its own. Kept
    separate from `probe_migrated_host_session` so the decision logic stays
    testable without a browser.

    `channel=None` means bundled Chromium; the kwarg is then omitted rather than
    passed as None.
    """
    from gflow_cli.browser_manager import ensure_profile_engine_compatible

    from .strategies import async_playwright

    async with ProfileLease(profile_dir):
        ensure_profile_engine_compatible(profile_dir, channel)
        async with async_playwright() as pw:
            kwargs: dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": True,
                "args": ["--password-store=basic"],
            }
            if channel is not None:
                kwargs["channel"] = channel
            ctx = await pw.chromium.launch_persistent_context(**kwargs)
            try:
                return await read_migrated_dom(ctx)
            finally:
                await ctx.close()


async def probe_migrated_host_session(
    profile_dir: Path,
    *,
    source: str,
    channel: str | None = None,
) -> FlowSessionStatus | None:
    """Confirm a Flow session against flow.google.com, or return None.

    For accounts Google moved to flow.google.com whose labs NextAuth session is
    never minted, the labs oracle reports GOOGLE_SESSION_ONLY forever and the
    account is locked out of gflow entirely (#791).

    This is server-attested, which cookie presence can never be: the app renders
    a sign-out link only when the server answered its bootstrap as a live
    session, so a revoked one (password change, "sign out of all devices") shows
    the anonymous shape. It costs a browser because nothing cheaper works —
    `GET /` and `/tools/flow` answer 200 identically to a stranger, and a
    batchexecute read without an `at` token is 401 even with a valid session,
    while `SNlM0e` is no longer in the body to scrape. All four measured in
    `docs/superpowers/spikes/2026-09-16-migrated-session-oracle-needs-a-browser.md`.

    Returns AUTHENTICATED with **user_email=None** — no email or GAIA id appears
    anywhere on that host, in either arm — or None, which leaves the caller's
    original outcome untouched. Fail-closed: any failure returns None.
    """
    if get_settings().flow_host == "labs.google":
        # Existing kill switch, no new env var. An operator who has pinned labs
        # has said not to touch the migrated host; honour that before launching.
        logger.info("auth_migrated_probe_skipped_labs_pinned", source=source)
        return None

    if channel is None:
        # The profile's own marker, not a hardcoded "chrome": a bundled-Chromium
        # profile would otherwise be refused by the engine check rather than probed.
        from gflow_cli.browser_manager import channel_for_profile

        channel = channel_for_profile(profile_dir)

    try:
        counts = await _render_migrated_dom(profile_dir, channel)
    except Exception as exc:  # noqa: BLE001
        # Fail-closed, and name the failure: a probe that cannot run must never
        # upgrade an outcome, but it must also not look like a clean negative.
        logger.warning("auth_migrated_probe_error", source=source, error=type(exc).__name__)
        return None

    if not evaluate_migrated_dom(counts):
        logger.info(
            "auth_migrated_probe_not_signed_in",
            source=source,
            signout_link=counts.get("signout_link", 0),
            signin_cta=counts.get("signin_cta", 0),
        )
        return None

    logger.warning(
        "auth_migrated_host_session_verified",
        source=source,
        detail="labs session absent; flow.google.com rendered an authenticated app",
    )
    return FlowSessionStatus(
        outcome=FlowSessionOutcome.AUTHENTICATED,
        user_email=None,
        source=source,
        flow_host_session=True,
    )


async def verify_flow_session(
    profile_dir: Path,
    *,
    channel: str | None = "chrome",
    source: str = "chrome",
) -> FlowSessionStatus:
    """Headlessly probe `profile_dir` for a usable Flow app session.

    NOTE: since PR #168, `verify_flow_profile` is the production entry point
    (`RealChromeStrategy.login` calls it): it reads cookies straight from
    Chrome's SQLite store via `browser_cookie3` and only launches Playwright
    when that decryption fails. This function is the original full-Playwright
    probe, retained for the tests and as a standalone verification primitive.

    Launches a headless persistent context on the profile, reads cookies, and
    calls the NextAuth session endpoint. Fail-closed: any failure — boundary
    violation aside — yields VERIFICATION_ERROR, never AUTHENTICATED.

    Precondition: `profile_dir` must resolve inside GFLOW_CLI_HOME. The check
    uses `strict=True` (the directory exists by the time verification runs);
    `RealChromeStrategy.login`'s own pre-`mkdir` check deliberately stays
    `strict=False` — see the design spec §4.2.
    """
    _validate_profile_in_home(profile_dir)

    # Lazy import — a top-level `from .strategies import ...` would create the
    # cycle strategies -> real_chrome -> verification -> strategies.
    from .strategies import async_playwright

    status_code: int
    body: str
    try:
        from gflow_cli.browser_manager import ensure_profile_engine_compatible

        # Own the profile for this headless probe context (D3). Lease is the
        # OUTER context so it releases only after the driver stops. Contention
        # raises ProfileLockedError before Chrome launches; the fail-closed
        # wrapper below maps it (like any probe failure) to VERIFICATION_ERROR.
        async with ProfileLease(profile_dir):
            # #477 guard AFTER the lease (a pre-wait check would validate a
            # 'Last Version' the holder rewrites as it releases): the probe
            # must not trigger downgrade cleanup either. Inside the
            # fail-closed wrapper, so the refusal maps to VERIFICATION_ERROR.
            ensure_profile_engine_compatible(profile_dir, channel)
            async with async_playwright() as pw:
                ctx = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel=channel,
                    headless=True,
                    args=["--password-store=basic"],
                )
                try:
                    cookies = await ctx.cookies()
                    google_session = any(c.get("name") == "SAPISID" for c in cookies)
                    flow_host_session = _has_flow_host_session(cookies)
                    status_code, body = await _fetch_session(ctx)
                    # #791: this context is already open, so confirming against
                    # flow.google.com costs a page load, not a launch. Decide
                    # here, while we still hold the browser.
                    migrated_counts: Mapping[str, int] | None = None
                    provisional = evaluate_session_response(
                        status_code,
                        body,
                        google_session=google_session,
                        source=source,
                        flow_host_session=flow_host_session,
                    )
                    if (
                        provisional.migrated_probe_warranted
                        and get_settings().flow_host != "labs.google"
                    ):
                        try:
                            migrated_counts = await read_migrated_dom(ctx)
                        except Exception as probe_exc:  # noqa: BLE001
                            # Keep the labs outcome. Letting this reach the outer
                            # handler would convert an accurate, actionable
                            # GOOGLE_SESSION_ONLY into VERIFICATION_ERROR, whose
                            # remediation says "check network connectivity" — a
                            # worse diagnosis than the one we already had. #795 is
                            # the precedent for a fallback's guard doing exactly this.
                            logger.warning(
                                "auth_migrated_probe_error",
                                source=source,
                                error=type(probe_exc).__name__,
                            )
                finally:
                    await ctx.close()
    # Fail-closed: any failure here yields VERIFICATION_ERROR, never AUTHENTICATED.
    except Exception as exc:
        logger.warning("auth_flow_session_probe_error", source=source, error=type(exc).__name__)
        return FlowSessionStatus(
            outcome=FlowSessionOutcome.VERIFICATION_ERROR,
            user_email=None,
            source=source,
        )

    result = evaluate_session_response(
        status_code,
        body,
        google_session=google_session,
        source=source,
        flow_host_session=flow_host_session,
    )
    if result.outcome is FlowSessionOutcome.VERIFICATION_ERROR:
        # Observable durability signal — distinguishes a moved/changed endpoint
        # from a flaky link. The status code is safe to log; the body is not.
        logger.warning(
            "auth_flow_session_unexpected_response",
            source=source,
            status_code=status_code,
        )
    if migrated_counts is not None and evaluate_migrated_dom(migrated_counts):
        logger.warning(
            "auth_migrated_host_session_verified",
            source=source,
            detail="labs session absent; flow.google.com rendered an authenticated app",
        )
        return FlowSessionStatus(
            outcome=FlowSessionOutcome.AUTHENTICATED,
            user_email=None,
            source=source,
            flow_host_session=True,
        )
    return result


async def verify_flow_profile(
    profile_dir: Path,
    *,
    source: str = "chrome",
) -> FlowSessionStatus:
    """Probe `profile_dir` for a usable Flow app session via the fast httpx path.

    Reads Chrome cookies directly from the SQLite store using browser_cookie3
    (falling back to a marker-gated Playwright context on decryption failure),
    then calls the NextAuth session endpoint with up to `_MAX_ATTEMPTS` attempts.
    Fail-closed: any failure yields VERIFICATION_ERROR, never AUTHENTICATED.
    """
    _validate_profile_in_home(profile_dir)

    status_code: int
    body: str
    try:
        (
            status_code,
            body,
            google_session,
            flow_host_session,
        ) = await fetch_flow_session_httpx(profile_dir)

    # #796: the marker gate is local profile state, not a network fault. It was
    # flattened into VERIFICATION_ERROR, whose remediation says "check network
    # connectivity" — wrong advice, and specifically wrong on a profile whose
    # marker a failed login had just rolled back (real_chrome.py:433-434).
    # `_validate_profile_in_home` raises SecurityError too, but above the try, so
    # a path violation still propagates instead of being classified here.
    except SecurityError:
        logger.warning("auth_profile_marker_missing", source=source)
        return FlowSessionStatus(
            outcome=FlowSessionOutcome.PROFILE_MARKER_MISSING,
            user_email=None,
            source=source,
        )

    # Fail-closed: any failure here yields VERIFICATION_ERROR, never AUTHENTICATED.
    except Exception as exc:
        logger.warning("auth_flow_session_probe_error", source=source, error=type(exc).__name__)
        return FlowSessionStatus(
            outcome=FlowSessionOutcome.VERIFICATION_ERROR,
            user_email=None,
            source=source,
        )

    result = evaluate_session_response(
        status_code,
        body,
        google_session=google_session,
        source=source,
        flow_host_session=flow_host_session,
    )
    if result.outcome is FlowSessionOutcome.VERIFICATION_ERROR:
        # Observable durability signal — distinguishes a moved/changed endpoint
        # from a flaky link. The status code is safe to log; the body is not.
        logger.warning(
            "auth_flow_session_unexpected_response",
            source=source,
            status_code=status_code,
        )
    if result.migrated_probe_warranted:
        # #791: labs declined, but this profile carries a flow.google.com
        # app-session cookie, so labs may simply never mint one for it. Confirm
        # against the host that actually serves the app before locking the
        # account out. Returns None on anything short of a clear positive, which
        # leaves `result` exactly as it was.
        migrated = await probe_migrated_host_session(profile_dir, source=source)
        if migrated is not None:
            return migrated
    return result
