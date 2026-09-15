@e2e @e2e_auth
Feature: A session Google moved to flow.google.com can still be verified
  # #791. For accounts Google migrated to flow.google.com whose labs NextAuth session is
  # never minted, the labs oracle returns GOOGLE_SESSION_ONLY forever. gflow then refuses
  # to do anything at all — not a degraded feature, a total lockout.
  #
  # These are e2e because the signal only exists in a RENDERED page. Measured 2026-09-16
  # (docs/superpowers/spikes/2026-09-16-migrated-session-oracle-needs-a-browser.md):
  #
  #   GET flow.google.com/ and /tools/flow   200 / 200, 39 and 47 byte deltas
  #   batchexecute read without an `at`      401 with a VALID session, 401 anonymous
  #   SNlM0e / any XSRF-shaped token         absent in both arms
  #   rendered signout_link / signin_cta     1 / 0  authenticated, 0 / 1  anonymous
  #
  # A mocked page cannot falsify any of this. The whole finding is that the response body
  # is identical for both arms and only Angular's post-boot render differs, so a fixture
  # that returns a hand-written DOM would pass against an oracle that reads the body —
  # which is exactly the broken design this replaces.
  #
  # Cost: zero. Navigation and DOM reads only; no generation, no entity created.

  Scenario: A real signed-in profile renders the authenticated anchors
    # The instrument itself, against live Flow. If Google restyles this page, this is the
    # test that goes red — not a user's login.
    Given a profile with a live Flow session
    When the driver reads the rendered flow.google.com DOM
    Then the sign-out anchor is present
    And the sign-in call to action is absent
    And the DOM is read as an authenticated session

  Scenario: A profile with no session renders the anonymous anchors
    # The control. Without it, "signout_link > 0" is a coincidence with formatting.
    Given a fresh profile with no Flow session
    When the driver reads the rendered flow.google.com DOM
    Then the sign-out anchor is absent
    And the DOM is not read as an authenticated session

  Scenario: The cookie gate opens only for a profile that has used flow.google.com
    # The gate decides whether a browser is spent at all. It must not fire for an account
    # that has never opened Flow, and it must not be mistaken for the oracle.
    Given a profile with a live Flow session
    When the driver reads the profile's cookie jar
    Then the flow-host session gate is open

  Scenario: Verification of a labs-alive profile is unchanged
    # The regression proof. Our account is migrated but labs still mints its session, so
    # it must take the ordinary path and never reach the probe.
    Given a profile with a live Flow session
    When the profile is verified
    Then the outcome is authenticated
    And the migrated probe was not warranted
