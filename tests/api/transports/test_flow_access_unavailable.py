# SPDX-License-Identifier: MIT
"""An account with no Flow entitlement is told so once, terminally.

Measured 2026-09-15 on a brand-new free Google account
(`scripts/dev/spike_flow_unavailable_signal.py`). gflow had no route for this state,
so five commands produced four different wrong diagnoses and one silent false
success:

    auth login    exit 8   "Flow app sign-in wasn't completed. Re-run ... until
                            the Flow editor loads"       <- cannot ever terminate
    auth status   exit 1   "Signed in to Google, but not to the Flow app."
    project list  exit 0   {"projects": [], "total": 0}  <- reports SUCCESS
    credits user  exit 3   "...See issue #795"           <- an unrelated real bug
    image t2i     exit 3   "Authentication expired ... Run `gflow auth login`"

Two of those send the user back into a login loop that can never complete.

**Why the anchor is a component tag and not the URL.** Three readings, all
pre-registered before the spike ran:

  * There is no entitlement field on the wire. The single keyword hit across 21
    responses was a marketing banner ("Google AI subscribers now receive 50
    additional Flow credits daily"), not a flag.
  * There is no HTTP 3xx. `flow.google.com/` answers **200** and Angular routes
    afterwards, client-side — so a status code cannot carry this.
  * The path is not stable: `/unavailable` and `/u/8/unavailable` were both seen,
    the second carrying Google's account-index segment.

What *is* stable is that Flow's own shell renders a dedicated component:
`aisandbox-root > router-outlet > flow-pinhole-unavailable-screen`. A component tag
is a Tier-1 anchor under AGENTS.md's locale-invariance rule, unlike the prose it
contains and unlike the path it happens to live at.

The browser-bound half of this behaviour is
`tests/features/landing_state_diagnosis.feature`, driven through a real Playwright
page. These tests pin the contract itself: the class, the message, the flag, the code.
"""

from __future__ import annotations

from typing import Any

import pytest

from gflow_cli.api.transports._common import raise_if_known_landing
from gflow_cli.errors import EXIT_CODE_MAP, FlowAccessUnavailableError, is_retryable

UNAVAILABLE = "flow-pinhole-unavailable-screen"


class _Locator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _Page:
    """Enough of Playwright's async Page for the landing check.

    `raise_if_known_landing` reads `.url` and queries one locator; anything else it
    touches would be a change in contract this stand-in should fail to satisfy.
    """

    def __init__(self, url: str, *, unavailable: int = 0, explode: bool = False) -> None:
        self.url = url
        self._unavailable = unavailable
        self._explode = explode
        self.queried: list[str] = []

    def locator(self, selector: str) -> _Locator:
        self.queried.append(selector)
        if self._explode:
            raise RuntimeError("locator engine unavailable")
        return _Locator(self._unavailable if selector == UNAVAILABLE else 0)


async def _raise_on(page: Any) -> BaseException | None:
    try:
        await raise_if_known_landing(page, requested="the Flow editor", at="test")
    except BaseException as exc:  # noqa: BLE001 - the raise IS the assertion
        return exc
    return None


# --------------------------------------------------------------------------- detection


async def test_the_unavailable_screen_raises_its_own_error() -> None:
    err = await _raise_on(_Page("https://flow.google.com/unavailable", unavailable=1))
    assert isinstance(err, FlowAccessUnavailableError), f"got {err!r}"


async def test_it_is_found_by_component_not_by_path() -> None:
    """The path varies; the component does not.

    `/u/8/unavailable` carries Google's account-index segment, and the bare
    `/unavailable` was measured on the same account minutes later. Both must raise,
    and a project page that merely *mentions* the word must not.
    """
    for url in (
        "https://flow.google.com/unavailable",
        "https://flow.google.com/u/8/unavailable",
        "https://flow.google.com/project/abc",  # component present, path says nothing
    ):
        err = await _raise_on(_Page(url, unavailable=1))
        assert isinstance(err, FlowAccessUnavailableError), f"{url}: {err!r}"


async def test_a_path_that_merely_looks_unavailable_does_not_fire() -> None:
    """The negative control. Without it, this suite cannot tell a working check
    from one that fires on everything — the failure mode that would break every
    healthy account."""
    err = await _raise_on(_Page("https://flow.google.com/project/unavailable-1234"))
    assert err is None, f"fired on a project page: {err!r}"


async def test_a_healthy_project_page_is_untouched() -> None:
    err = await _raise_on(_Page("https://flow.google.com/project/e2e"))
    assert err is None, f"fired on a healthy page: {err!r}"


async def test_a_probe_failure_never_displaces_the_real_diagnosis() -> None:
    """Totality, which this function's docstring already promises its URL half.

    A DOM probe that raises must not become the reported failure — the caller is
    already mid-diagnosis and its own reading is the one the operator needs.
    """
    err = await _raise_on(_Page("https://flow.google.com/project/e2e", explode=True))
    assert err is None, f"a broken locator engine displaced the caller's failure: {err!r}"


# --------------------------------------------------------------------------- the message


async def test_the_message_names_the_requirement_the_user_can_act_on() -> None:
    err = await _raise_on(_Page("https://flow.google.com/unavailable", unavailable=1))
    assert err is not None
    text = f"{err} {getattr(err, 'remediation_hint', '') or ''}".casefold()
    assert "subscription" in text or "google ai" in text, text
    assert "support.google.com/flow/answer/16353333" in text, (
        "cite Google's own eligibility page rather than paraphrasing rules that "
        "change — region, age and plan are all requirements and only one of them "
        "was measured here"
    )


async def test_the_message_does_not_send_the_user_back_to_login() -> None:
    err = await _raise_on(_Page("https://flow.google.com/unavailable", unavailable=1))
    assert err is not None
    text = f"{err} {getattr(err, 'remediation_hint', '') or ''}".casefold()
    for claim in ("auth login", "sign in again", "expired", "re-run"):
        assert claim not in text, f"re-opens the loop this class exists to close ({claim!r})"


async def test_it_says_what_it_saw() -> None:
    err = await _raise_on(_Page("https://flow.google.com/u/8/unavailable", unavailable=1))
    assert "flow.google.com/u/8/unavailable" in str(err), str(err)


# --------------------------------------------------------------------------- the contract


async def test_it_is_terminal() -> None:
    err = await _raise_on(_Page("https://flow.google.com/unavailable", unavailable=1))
    assert err is not None
    assert is_retryable(err) is False, (
        "reproduced on demand on a real account: repeated `gflow auth login` gave "
        "the identical exit 8 every time. A retry cannot help."
    )


def test_it_has_its_own_exit_code() -> None:
    code = EXIT_CODE_MAP[FlowAccessUnavailableError]
    assert code == 39
    assert code not in {3, 8, 23, 31}, (
        "3 and 8 are what the bug reported (auth expired / auth missing), 23 is "
        "'file a frontend bug' and 31 is Flow serving the wrong page for an "
        "unmeasured reason. A distinct state needs a distinct code or no script "
        "can branch on it."
    )


@pytest.mark.parametrize("other", ["signin", "public", "chooser"])
def test_the_existing_landing_kinds_keep_their_codes(other: str) -> None:
    """Guards the refactor, not the feature.

    Re-routing a raise changes its class and flags for free, which is how a
    refactor smuggles in an assertion nobody reviewed. These three shapes predate
    this change and must come out the other side unaltered.
    """
    from gflow_cli.api.transports._common import flow_landing_kind

    urls = {
        "signin": "https://labs.google/fx/api/auth/signin?error=Callback",
        "public": "https://flow.google.com/about",
        "chooser": "https://accounts.google.com/v3/signin/accountchooser?continue=x",
    }
    assert flow_landing_kind(urls[other]) == other


def test_the_mcp_twin_gets_the_same_verdict_and_not_the_fallback() -> None:
    """The queued surface is different code, so it is checked separately (AGENTS.md
    § the second law).

    `worker/daemon.py` does not know this class; it resolves an exit code by walking
    `EXIT_CODE_MAP` and taking the first `isinstance` hit, falling back to **1**. A
    class registered in the map but shadowed by an earlier, broader entry would reach
    an agent as a generic failure with no remediation, and every CLI test above would
    still pass. So this asserts the walk, in daemon order, rather than the dict lookup.
    """
    from gflow_cli.errors import UiSelectorDriftError

    def worker_exit_code(exc: Exception) -> int:
        # Byte-for-byte the daemon's resolution (worker/daemon.py, "Task execution
        # failed" branch). Duplicated deliberately: importing the daemon drags in the
        # queue, and the thing under test is the walk, not the daemon.
        return next((c for cls, c in EXIT_CODE_MAP.items() if isinstance(exc, cls)), 1)

    assert worker_exit_code(FlowAccessUnavailableError(detail="x")) == 39
    # Positive control: the walk really can return something else, so a passing
    # assertion above is not just "everything resolves to 39".
    assert worker_exit_code(UiSelectorDriftError(detail="x")) == EXIT_CODE_MAP[UiSelectorDriftError]
    assert worker_exit_code(ValueError("not ours")) == 1
