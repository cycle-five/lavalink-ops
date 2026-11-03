"""HTTP-level tests for the auth gate: ``BasicAuthMiddleware`` allowlist,
login/logout, cookie attributes, and the 429 path.

The pure helpers in ``test_auth.py`` were already well covered; their
*wiring* — the part that actually keeps the panel private — was not tested
at all. These use the real app via TestClient without entering the lifespan
(see ``conftest.client``), and mock nothing about auth itself.
"""

import pytest

from app import main as main_mod


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    main_mod._login_failures.clear()
    yield
    main_mod._login_failures.clear()


def test_unauthenticated_root_redirects_to_login_303(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_unauthenticated_hx_request_returns_401_with_hx_redirect(client):
    res = client.get("/", headers={"HX-Request": "true"}, follow_redirects=False)
    assert res.status_code == 401
    assert res.headers["HX-Redirect"] == "/login"


def test_login_page_bypasses_auth(client):
    res = client.get("/login")
    assert res.status_code == 200


def test_healthz_bypasses_auth(client):
    # Probes will fail (no upstream running) but must not redirect to login:
    # the aggregate answers 503, not 303.
    res = client.get("/healthz", follow_redirects=False)
    assert res.status_code in (200, 503)


def test_health_dashboard_does_not_bypass_auth(client):
    res = client.get("/health", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_authed_client_can_reach_dashboard(authed_client):
    # Dashboard itself degrades gracefully when Lavalink is unreachable
    # (renders with an error string), so an authed request is a 200.
    res = authed_client.get("/", follow_redirects=False)
    assert res.status_code == 200


def test_tampered_cookie_redirects(client):
    client.cookies.set("admin_session", "123.deadbeef." + "0" * 64)
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303


def test_do_login_success_sets_httponly_lax_cookie_and_redirects(client):
    res = client.post(
        "/do-login",
        data={"password": "test-admin-password"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/"
    cookie = res.headers["set-cookie"]
    assert "admin_session=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert f"max-age={main_mod.SESSION_MAX_AGE_SECONDS}" in cookie.lower()


def test_do_login_success_clears_prior_failures(client):
    for _ in range(2):
        client.post("/do-login", data={"password": "wrong"}, follow_redirects=False)
    assert main_mod._login_failures.get("testclient")
    res = client.post(
        "/do-login", data={"password": "test-admin-password"}, follow_redirects=False
    )
    assert res.status_code == 303
    assert not main_mod._login_failures.get("testclient")


def test_do_login_wrong_password_401_and_records_failure(client):
    res = client.post("/do-login", data={"password": "nope"}, follow_redirects=False)
    assert res.status_code == 401
    assert main_mod._login_failures.get("testclient")


def test_do_login_empty_password_rejected(client):
    res = client.post("/do-login", data={"password": ""}, follow_redirects=False)
    assert res.status_code == 401


def test_do_login_rate_limited_returns_429(client):
    for _ in range(main_mod.LOGIN_MAX_FAILURES):
        main_mod._record_login_failure("testclient")
    res = client.post(
        "/do-login", data={"password": "test-admin-password"}, follow_redirects=False
    )
    assert res.status_code == 429


def test_logout_deletes_cookie_and_redirects(authed_client):
    res = authed_client.post("/logout", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"
    assert "admin_session=" in res.headers["set-cookie"]


def test_session_token_at_exactly_max_age_rejected(monkeypatch):
    import hashlib
    import hmac as _hmac
    import time

    secret = "test-secret-key"
    issued = int(time.time()) - main_mod.SESSION_MAX_AGE_SECONDS
    payload = f"{issued}.deadbeef"
    sig = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # age == max_age is outside `0 <= age < MAX`, so it must be rejected.
    assert not main_mod._verify_session(f"{payload}.{sig}", secret)


def test_verify_session_none_rejected():
    assert not main_mod._verify_session(None, "whatever")
