"""Migrated-host session oracle (#791).

Every assertion here is bound to a measurement in
`docs/superpowers/spikes/2026-09-16-migrated-session-oracle-needs-a-browser.md`:

  authenticated   signout_link=1  signin_cta=0
  anonymous       signout_link=0  signin_cta=1

and to the fact that no *browserless* instrument separates those arms — the raw
HTML carries `signin_cta` in BOTH, so only the rendered DOM can decide.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gflow_cli.auth.cookies import ChromeCookieSnapshot, _has_flow_host_session
from gflow_cli.auth.verification import (
    FlowSessionOutcome,
    FlowSessionStatus,
    evaluate_migrated_dom,
    evaluate_session_response,
    probe_migrated_host_session,
    verify_flow_profile,
)
from gflow_cli.errors import SecurityError

AUTHENTICATED_BODY = (
    '{"user": {"name": "T", "email": "t@example.com"}, "expires": "2026-06-16T08:39:21.000Z"}'
)
EMPTY_BODY = "{}"


def _cookie(name: str, domain: str) -> dict[str, str]:
    return {"name": name, "value": "x", "domain": domain}


class TestFlowHostSessionCookie:
    """The cheap gate — derived from the jar BOTH readers already hold."""

    @pytest.mark.parametrize("name", ["__Secure-OSID", "OSID"])
    def test_flow_host_cookie_on_flow_domain(self, name: str) -> None:
        assert _has_flow_host_session([_cookie(name, ".flow.google.com")]) is True

    def test_same_cookie_on_a_different_google_host_does_not_count(self) -> None:
        # OSID exists on plain google.com for every signed-in Google user. Counting
        # it would make the gate fire for accounts that never saw Flow at all.
        assert _has_flow_host_session([_cookie("OSID", ".google.com")]) is False

    def test_unrelated_flow_cookie_does_not_count(self) -> None:
        assert _has_flow_host_session([_cookie("NID", ".flow.google.com")]) is False

    def test_empty_jar(self) -> None:
        assert _has_flow_host_session([]) is False

    def test_snapshot_defaults_false(self) -> None:
        # Back-compat: every existing construction site keeps working.
        snap = ChromeCookieSnapshot(httpx_cookies={}, google_session=False)
        assert snap.flow_host_session is False


class TestProbeGate:
    """Which outcomes warrant the (expensive) browser probe, and which never do."""

    def test_google_session_only_with_flow_cookies_warrants_a_probe(self) -> None:
        status = evaluate_session_response(
            200, EMPTY_BODY, google_session=True, source="chrome", flow_host_session=True
        )
        assert status.outcome is FlowSessionOutcome.GOOGLE_SESSION_ONLY
        assert status.migrated_probe_warranted is True

    def test_verification_error_with_flow_cookies_warrants_a_probe(self) -> None:
        """The widened trigger. Predict: 'otherwise the fallback switches off on
        the day labs actually dies, which is the scenario it exists for.'"""
        status = evaluate_session_response(
            500, "", google_session=True, source="chrome", flow_host_session=True
        )
        assert status.outcome is FlowSessionOutcome.VERIFICATION_ERROR
        assert status.migrated_probe_warranted is True

    def test_no_flow_cookies_never_warrants_a_probe(self) -> None:
        status = evaluate_session_response(
            200, EMPTY_BODY, google_session=True, source="chrome", flow_host_session=False
        )
        assert status.migrated_probe_warranted is False

    def test_authenticated_never_re_probes(self) -> None:
        status = evaluate_session_response(
            200, AUTHENTICATED_BODY, google_session=True, source="chrome", flow_host_session=True
        )
        assert status.outcome is FlowSessionOutcome.AUTHENTICATED
        assert status.migrated_probe_warranted is False

    def test_no_session_never_probes(self) -> None:
        """No SAPISID means signed out of Google entirely — a browser cannot help."""
        status = evaluate_session_response(
            200, EMPTY_BODY, google_session=False, source="chrome", flow_host_session=True
        )
        assert status.outcome is FlowSessionOutcome.NO_SESSION
        assert status.migrated_probe_warranted is False

    def test_default_keeps_existing_callers_unchanged(self) -> None:
        status = evaluate_session_response(200, EMPTY_BODY, google_session=True, source="chrome")
        assert status.migrated_probe_warranted is False


class TestEvaluateMigratedDom:
    """Pure reading of the rendered DOM. Fail-closed on anything ambiguous."""

    def test_authenticated_shape_measured_by_the_spike(self) -> None:
        assert evaluate_migrated_dom({"signout_link": 1, "signin_cta": 0}) is True

    def test_anonymous_shape_measured_by_the_spike(self) -> None:
        assert evaluate_migrated_dom({"signout_link": 0, "signin_cta": 1}) is False

    def test_neither_anchor_is_not_authenticated(self) -> None:
        """A page that has not finished booting shows neither. Never guess."""
        assert evaluate_migrated_dom({"signout_link": 0, "signin_cta": 0}) is False

    def test_both_anchors_is_not_authenticated(self) -> None:
        """Contradictory: an account chooser can render both. Fail closed."""
        assert evaluate_migrated_dom({"signout_link": 1, "signin_cta": 1}) is False

    def test_missing_keys_fail_closed(self) -> None:
        assert evaluate_migrated_dom({}) is False


class TestProbeKillSwitch:
    """`GFLOW_CLI_FLOW_HOST=labs.google` means never touch the migrated host."""

    @staticmethod
    def _profile(tmp_path: Path) -> Path:
        # Must live inside the patched home: the probe validates its own boundary.
        profile = tmp_path / "profile_x"
        profile.mkdir(exist_ok=True)
        return profile

    @pytest.mark.asyncio
    async def test_labs_only_setting_skips_the_probe_entirely(self, tmp_path: Path) -> None:
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch("gflow_cli.auth.verification._render_migrated_dom", new=AsyncMock()) as render,
        ):
            settings.return_value = MagicMock(flow_host="labs.google", home=tmp_path)
            result = await probe_migrated_host_session(self._profile(tmp_path), source="chrome")
        assert result is None
        render.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authenticated_dom_yields_authenticated_with_no_email(
        self, tmp_path: Path
    ) -> None:
        """The spike measured no email anywhere on the migrated host, in either
        arm — so this outcome MUST carry user_email=None rather than invent one."""
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification._render_migrated_dom",
                new=AsyncMock(return_value={"signout_link": 1, "signin_cta": 0}),
            ),
        ):
            settings.return_value = MagicMock(flow_host="auto", home=tmp_path)
            result = await probe_migrated_host_session(self._profile(tmp_path), source="chrome")
        assert result is not None
        assert result.outcome is FlowSessionOutcome.AUTHENTICATED
        assert result.user_email is None

    @pytest.mark.asyncio
    async def test_anonymous_dom_returns_none_so_caller_keeps_its_outcome(
        self, tmp_path: Path
    ) -> None:
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification._render_migrated_dom",
                new=AsyncMock(return_value={"signout_link": 0, "signin_cta": 1}),
            ),
        ):
            settings.return_value = MagicMock(flow_host="auto", home=tmp_path)
            result = await probe_migrated_host_session(self._profile(tmp_path), source="chrome")
        assert result is None

    @pytest.mark.asyncio
    async def test_probe_failure_is_fail_closed_alone(self, tmp_path: Path) -> None:
        """A browser that will not start must never upgrade an outcome."""
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification._render_migrated_dom",
                new=AsyncMock(side_effect=RuntimeError("no chrome")),
            ),
        ):
            settings.return_value = MagicMock(flow_host="auto", home=tmp_path)
            result = await probe_migrated_host_session(self._profile(tmp_path), source="chrome")
        assert result is None


class TestVerifyFlowProfileIntegration:
    """How `verify_flow_profile` uses the probe — the wiring, not the probe."""

    @staticmethod
    def _profile(tmp_path: Path) -> Path:
        profile = tmp_path / "profile_x"
        profile.mkdir()
        return profile

    @pytest.mark.asyncio
    async def test_a_failed_probe_keeps_the_labs_outcome(self, tmp_path: Path) -> None:
        """The #795 trap: a fallback's guard must not discard a better diagnosis.

        GOOGLE_SESSION_ONLY is accurate and actionable. VERIFICATION_ERROR tells
        the user to check network connectivity. A probe that could not run must
        never turn the first into the second.
        """
        profile = self._profile(tmp_path)
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification.fetch_flow_session_httpx",
                new=AsyncMock(return_value=(200, "{}", True, True)),
            ),
            patch(
                "gflow_cli.auth.verification.probe_migrated_host_session",
                new=AsyncMock(return_value=None),
            ),
        ):
            settings.return_value.home = tmp_path
            status = await verify_flow_profile(profile, source="chrome")
        assert status.outcome is FlowSessionOutcome.GOOGLE_SESSION_ONLY

    @pytest.mark.asyncio
    async def test_a_successful_probe_upgrades_to_authenticated(self, tmp_path: Path) -> None:
        profile = self._profile(tmp_path)
        rescued = FlowSessionStatus(
            outcome=FlowSessionOutcome.AUTHENTICATED,
            user_email=None,
            source="chrome",
            flow_host_session=True,
        )
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification.fetch_flow_session_httpx",
                new=AsyncMock(return_value=(200, "{}", True, True)),
            ),
            patch(
                "gflow_cli.auth.verification.probe_migrated_host_session",
                new=AsyncMock(return_value=rescued),
            ),
        ):
            settings.return_value.home = tmp_path
            status = await verify_flow_profile(profile, source="chrome")
        assert status.outcome is FlowSessionOutcome.AUTHENTICATED
        assert status.user_email is None

    @pytest.mark.asyncio
    async def test_no_flow_cookie_means_no_browser_is_ever_launched(self, tmp_path: Path) -> None:
        """The cost guarantee. Ordinary verification must not pay for a browser."""
        profile = self._profile(tmp_path)
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification.fetch_flow_session_httpx",
                new=AsyncMock(return_value=(200, "{}", True, False)),
            ),
            patch(
                "gflow_cli.auth.verification.probe_migrated_host_session", new=AsyncMock()
            ) as probe,
        ):
            settings.return_value.home = tmp_path
            status = await verify_flow_profile(profile, source="chrome")
        assert status.outcome is FlowSessionOutcome.GOOGLE_SESSION_ONLY
        probe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_authenticated_labs_answer_never_probes(self, tmp_path: Path) -> None:
        profile = self._profile(tmp_path)
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch(
                "gflow_cli.auth.verification.fetch_flow_session_httpx",
                new=AsyncMock(return_value=(200, AUTHENTICATED_BODY, True, True)),
            ),
            patch(
                "gflow_cli.auth.verification.probe_migrated_host_session", new=AsyncMock()
            ) as probe,
        ):
            settings.return_value.home = tmp_path
            status = await verify_flow_profile(profile, source="chrome")
        assert status.outcome is FlowSessionOutcome.AUTHENTICATED
        assert status.user_email == "t@example.com"
        probe.assert_not_awaited()


class TestProbeLaunchHardening:
    """Security properties of the launch itself — pinned so they cannot drift."""

    @pytest.mark.asyncio
    async def test_service_workers_are_blocked(self, tmp_path: Path) -> None:
        """A service worker at flow.google.com scope could answer the probe's
        navigation from Cache Storage with the shape this profile saw when it WAS
        signed in — making a revoked session read as live, which is the single
        failure this oracle exists to prevent.

        Found by council D3 on PR #835: the spike's anonymous arm used a cold
        throwaway profile while the authenticated arm was warm, so the control
        could not distinguish "server said anonymous" from "empty cache".
        """
        profile = tmp_path / "profile_x"
        profile.mkdir()
        launched: dict[str, object] = {}

        class _Ctx:
            async def close(self) -> None: ...

        class _Chromium:
            async def launch_persistent_context(self, **kwargs: object) -> _Ctx:
                launched.update(kwargs)
                return _Ctx()

        class _PW:
            chromium = _Chromium()

            async def __aenter__(self) -> _PW:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch("gflow_cli.auth.strategies.async_playwright", return_value=_PW()),
            patch("gflow_cli.browser_manager.channel_for_profile", return_value="chrome"),
            patch("gflow_cli.browser_manager.ensure_profile_engine_compatible"),
            patch("gflow_cli.auth.verification.ProfileLease"),
            patch(
                "gflow_cli.auth.verification.read_migrated_dom",
                new=AsyncMock(return_value={"signout_link": 0, "signin_cta": 1}),
            ),
        ):
            settings.return_value = MagicMock(flow_host="auto", home=tmp_path)
            await probe_migrated_host_session(profile, source="chrome")

        assert launched.get("service_workers") == "block", (
            f"the probe must block service workers; launch kwargs were {launched}"
        )
        assert launched.get("headless") is True

    @pytest.mark.asyncio
    async def test_a_profile_outside_home_is_refused(self, tmp_path: Path) -> None:
        """The probe guards its own boundary rather than trusting its caller."""
        home = tmp_path / "home"
        home.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch("gflow_cli.auth.verification._render_migrated_dom", new=AsyncMock()) as render,
        ):
            settings.return_value = MagicMock(flow_host="auto", home=home)
            with pytest.raises(SecurityError):
                await probe_migrated_host_session(outside, source="chrome")
        render.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_markerless_profile_is_refused_rather_than_opened(self, tmp_path: Path) -> None:
        """A failed first login rolls `.gflow_browser_strategy` back — the exact
        state #791's reporters are likely in. Without this gate, BUNDLED Chromium
        would open a real-Chrome profile and write its own `Last Version` into it,
        which is the corruption the marker exists to prevent. Every sibling reader
        refuses here; so does the probe. Fail-closed: the caller sees None.
        """
        profile = tmp_path / "profile_x"
        profile.mkdir()
        launched: list[object] = []

        class _Chromium:
            async def launch_persistent_context(self, **kwargs: object) -> object:
                launched.append(kwargs)
                raise AssertionError("must not launch on a markerless profile")

        class _PW:
            chromium = _Chromium()

            async def __aenter__(self) -> _PW:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

        with (
            patch("gflow_cli.auth.verification.get_settings") as settings,
            patch("gflow_cli.auth.strategies.async_playwright", return_value=_PW()),
            patch("gflow_cli.browser_manager.channel_for_profile", return_value=None),
            patch("gflow_cli.auth.verification.ProfileLease"),
        ):
            settings.return_value = MagicMock(flow_host="auto", home=tmp_path)
            result = await probe_migrated_host_session(profile, source="chrome")

        assert result is None, "a refused probe must never upgrade the outcome"
        assert launched == [], f"no browser may start on a markerless profile; got {launched}"
