"""E2E for the migrated-host session oracle (#791).

Binds ``tests/features/migrated_session_oracle.feature``. The Gherkin's ``@e2e`` tags
become pytest markers via pytest-bdd, so ``-m e2e`` / ``-m e2e_auth`` select this file
exactly like a hand-written e2e — see ``docs/E2E_TESTING.md`` § BDD-bound e2e.

**Why an e2e and not a unit test.** The entire finding behind #791's fix is that
flow.google.com's HTTP *response* is identical for an authenticated client and a
stranger — 200 either way, 39 bytes apart, `signin_cta` present in both raw bodies, no
`SNlM0e`, and a batchexecute read returning 401 even with a valid session. Only what
Angular renders after boot differs. A fixture serving hand-written HTML would therefore
pass against an oracle that greps the response body, which is precisely the broken design
this replaces. Only a real browser against real Flow can falsify it.

**Cost: zero.** Navigation and DOM reads only. No generation, no entity created, nothing
to clean up.

**What this canNOT cover, and why that is a named blocker rather than a gap.** The happy
path #791 actually reports — labs dead, migrated probe rescues the login — needs an
account in a cohort Google has not put this machine in. Every profile here is migrated
*with labs alive*. So these scenarios verify the instrument and the regression; the
end-to-end rescue is verified by the reporter. Per the Iron Law that is a permitted,
named external blocker, and the fix ships ``Refs #791`` rather than ``Closes``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from playwright.async_api import async_playwright
from pytest_bdd import given, scenarios, then, when

from gflow_cli.auth.cookies import _has_flow_host_session
from gflow_cli.auth.verification import (
    FlowSessionOutcome,
    evaluate_migrated_dom,
    read_migrated_dom,
    verify_flow_profile,
)
from gflow_cli.browser_manager import channel_for_profile
from gflow_cli.profile_lease import ProfileLease

scenarios("../features/migrated_session_oracle.feature")


@pytest.fixture
def world() -> dict[str, Any]:
    return {}


async def _read_dom(profile_dir: Path, *, channel: str | None) -> dict[str, int]:
    """Open the profile headlessly and read the rendered anchors.

    Goes through the same `read_migrated_dom` the production probe uses — a
    re-implementation here would test the test.
    """
    async with ProfileLease(profile_dir), async_playwright() as pw:
        kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": True,
            "args": ["--password-store=basic"],
            # Match production: a cached service worker could serve the shape this
            # profile saw when signed in, which is the one thing the oracle must
            # never read as live.
            "service_workers": "block",
        }
        if channel is not None:
            kwargs["channel"] = channel
        ctx = await pw.chromium.launch_persistent_context(**kwargs)
        try:
            return dict(await read_migrated_dom(ctx))
        finally:
            await ctx.close()


@given("a profile with a live Flow session")
def _live_profile(world: dict[str, Any], e2e_profile_dir: Path) -> None:
    world["profile"] = e2e_profile_dir
    world["channel"] = channel_for_profile(e2e_profile_dir)


@given("a fresh profile with no Flow session")
def _fresh_profile(world: dict[str, Any], e2e_nosession_profile: Path) -> None:
    # A fresh dir has no `.gflow_browser_strategy` marker, so there is no channel
    # to pin and bundled Chromium is the right engine. (Production's
    # `_render_migrated_dom` REFUSES a markerless profile outright; this arm is the
    # anonymous control, not a production path, so it launches directly.)
    world["profile"] = e2e_nosession_profile
    world["channel"] = None


async def _read_jar_async(profile_dir: Path, channel: str | None) -> bool:
    async with ProfileLease(profile_dir), async_playwright() as pw:
        kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": True,
            "args": ["--password-store=basic"],
            # Match production: a cached service worker could serve the shape this
            # profile saw when signed in, which is the one thing the oracle must
            # never read as live.
            "service_workers": "block",
        }
        if channel is not None:
            kwargs["channel"] = channel
        ctx = await pw.chromium.launch_persistent_context(**kwargs)
        try:
            # Full jar, never ctx.cookies([url]) — that path filter drops
            # path-scoped tokens (#222/#230).
            return _has_flow_host_session(await ctx.cookies())
        finally:
            await ctx.close()


# pytest-bdd does not await async step functions — it calls them and discards the
# coroutine, so an async step silently never runs and every assertion downstream
# reads an empty `world`. Steps stay sync and drive async work through asyncio.run,
# the same way tests/e2e/test_click_attribution_bdd.py does.


@when("the driver reads the rendered flow.google.com DOM")
def _read(world: dict[str, Any]) -> None:
    world["dom"] = asyncio.run(_read_dom(world["profile"], channel=world["channel"]))


@when("the driver reads the profile's cookie jar")
def _read_jar(world: dict[str, Any]) -> None:
    world["gate"] = asyncio.run(_read_jar_async(world["profile"], world["channel"]))


@when("the profile is verified")
def _verify(world: dict[str, Any]) -> None:
    world["status"] = asyncio.run(verify_flow_profile(world["profile"], source="chrome"))


@then("the sign-out anchor is present")
def _signout_present(world: dict[str, Any]) -> None:
    assert world["dom"]["signout_link"] > 0, (
        f"expected a rendered sign-out anchor on a signed-in profile, got {world['dom']}. "
        "If this is 0 on a working session, flow.google.com has restyled its account "
        "menu and the oracle's anchor needs re-measuring — re-run "
        "scripts/dev/spike_migrated_session_oracle.py."
    )


@then("the sign-in call to action is absent")
def _signin_absent(world: dict[str, Any]) -> None:
    assert world["dom"]["signin_cta"] == 0, (
        f"a signed-in profile must not render a sign-in CTA, got {world['dom']}"
    )


@then("the DOM is read as an authenticated session")
def _reads_authenticated(world: dict[str, Any]) -> None:
    assert evaluate_migrated_dom(world["dom"]) is True


@then("the sign-out anchor is absent")
def _signout_absent(world: dict[str, Any]) -> None:
    assert world["dom"]["signout_link"] == 0, (
        f"a profile with no session must not render a sign-out anchor, got {world['dom']}. "
        "A non-zero count here would mean the anchor is not session-dependent at all, "
        "which would invalidate the oracle."
    )


@then("the sign-in call to action is present")
def _signin_present(world: dict[str, Any]) -> None:
    assert world["dom"]["signin_cta"] > 0, (
        f"the anonymous control must POSITIVELY render a sign-in CTA, got {world['dom']}. "
        "0/0 would mean the page never loaded — which would make this arm pass against "
        "a driver that navigated nowhere, and the whole control worthless."
    )


@then("the DOM is not read as an authenticated session")
def _reads_anonymous(world: dict[str, Any]) -> None:
    assert evaluate_migrated_dom(world["dom"]) is False


@then("the flow-host session gate is open")
def _gate_open(world: dict[str, Any]) -> None:
    assert world["gate"] is True, (
        "a profile that has used flow.google.com must carry an app-session cookie "
        "on that host; without it the probe would never be reached"
    )


@then("the outcome is authenticated")
def _authenticated(world: dict[str, Any]) -> None:
    assert world["status"].outcome is FlowSessionOutcome.AUTHENTICATED, (
        f"expected AUTHENTICATED, got {world['status'].outcome}"
    )


@then("the migrated probe was not warranted")
def _probe_not_warranted(world: dict[str, Any]) -> None:
    # The regression assertion. labs answered, so the expensive path must stay shut
    # — if this ever flips True on a labs-alive profile, the gate has widened and
    # every ordinary verification is paying for a browser.
    assert world["status"].migrated_probe_warranted is False
