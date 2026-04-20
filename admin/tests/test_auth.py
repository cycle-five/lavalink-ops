import time

import pytest

from app.main import (
    LOGIN_MAX_FAILURES,
    LOGIN_WINDOW_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    _login_failures,
    _login_rate_limited,
    _record_login_failure,
    _clear_login_failures,
    _sign_session,
    _verify_session,
)


SECRET = "test-secret-key"


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    _login_failures.clear()
    yield
    _login_failures.clear()


# --- Session signing / verification -----------------------------------------


def test_fresh_token_verifies():
    token = _sign_session(SECRET)
    assert _verify_session(token, SECRET)


def test_different_logins_produce_different_tokens():
    a = _sign_session(SECRET)
    b = _sign_session(SECRET)
    assert a != b


def test_wrong_secret_rejected():
    token = _sign_session(SECRET)
    assert not _verify_session(token, "other-secret")


def test_tampered_signature_rejected():
    token = _sign_session(SECRET)
    flipped = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert not _verify_session(flipped, SECRET)


def test_tampered_timestamp_rejected():
    ts, nonce, sig = _sign_session(SECRET).split(".", 2)
    forged = f"{int(ts) - 10}.{nonce}.{sig}"
    assert not _verify_session(forged, SECRET)


@pytest.mark.parametrize("bad", ["", "not.a.token", "only.two", "a.b.c.d"])
def test_malformed_tokens_rejected(bad):
    assert not _verify_session(bad, SECRET)


def test_non_integer_timestamp_rejected():
    token = f"notanint.abcdef.{'0' * 64}"
    assert not _verify_session(token, SECRET)


def test_expired_token_rejected():
    issued = int(time.time()) - (SESSION_MAX_AGE_SECONDS + 60)
    nonce = "deadbeef"
    # Build a cookie with a valid HMAC but old issued_at
    import hashlib
    import hmac as _hmac

    payload = f"{issued}.{nonce}"
    sig = _hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert not _verify_session(f"{payload}.{sig}", SECRET)


def test_future_dated_token_rejected():
    issued = int(time.time()) + 3600
    nonce = "deadbeef"
    import hashlib
    import hmac as _hmac

    payload = f"{issued}.{nonce}"
    sig = _hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert not _verify_session(f"{payload}.{sig}", SECRET)


# --- Login rate limiter -----------------------------------------------------


def test_rate_limit_allows_up_to_threshold():
    for _ in range(LOGIN_MAX_FAILURES - 1):
        _record_login_failure("1.2.3.4")
    assert not _login_rate_limited("1.2.3.4")


def test_rate_limit_trips_at_threshold():
    for _ in range(LOGIN_MAX_FAILURES):
        _record_login_failure("1.2.3.4")
    assert _login_rate_limited("1.2.3.4")


def test_rate_limit_is_per_ip():
    for _ in range(LOGIN_MAX_FAILURES):
        _record_login_failure("1.2.3.4")
    assert not _login_rate_limited("5.6.7.8")


def test_clear_resets_counter():
    for _ in range(LOGIN_MAX_FAILURES):
        _record_login_failure("1.2.3.4")
    _clear_login_failures("1.2.3.4")
    assert not _login_rate_limited("1.2.3.4")


def test_old_attempts_prune_out_of_window():
    # Inject timestamps from well outside the window
    stale = time.time() - (LOGIN_WINDOW_SECONDS * 2)
    for _ in range(LOGIN_MAX_FAILURES):
        _login_failures["stale-ip"].append(stale)
    assert not _login_rate_limited("stale-ip")


def test_unknown_ip_does_not_grow_map():
    _login_rate_limited("1.1.1.1")
    _login_rate_limited("2.2.2.2")
    _login_rate_limited("3.3.3.3")
    # The lookup path must not create entries for IPs that never failed.
    assert "1.1.1.1" not in _login_failures
    assert "2.2.2.2" not in _login_failures
    assert "3.3.3.3" not in _login_failures


def test_pruning_removes_fully_expired_entries():
    stale = time.time() - (LOGIN_WINDOW_SECONDS * 2)
    _login_failures["gone"].append(stale)
    _login_rate_limited("gone")
    assert "gone" not in _login_failures
