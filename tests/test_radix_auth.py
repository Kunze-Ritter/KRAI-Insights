"""Unit tests for RadixAuthManager (no network)."""

import time

import pytest
from insights.etl.radix.auth import RadixAuthError, RadixAuthManager


def _mgr(tmp_path, **overrides) -> RadixAuthManager:
    kwargs = dict(
        base_url="https://radix.example/IM.RxPlusService.Api",
        username="u",
        password_base64="cHc=",
        client_code="c",
        license_id="l",
        cache_path=tmp_path / "radix_token.json",
        refresh_margin_seconds=60,
    )
    kwargs.update(overrides)
    return RadixAuthManager(**kwargs)


def test_missing_credentials_raises(tmp_path) -> None:
    with pytest.raises(RadixAuthError):
        _mgr(tmp_path, username="")


def test_parse_login_response_relative_expiry() -> None:
    token, exp = RadixAuthManager._parse_login_response({"token": "abc", "expiresIn": 3600})
    assert token == "abc"
    assert pytest.approx(exp, abs=5) == time.time() + 3600


def test_parse_login_response_alt_token_key() -> None:
    token, _ = RadixAuthManager._parse_login_response({"accessToken": "xyz", "expires_in": 10})
    assert token == "xyz"


def test_parse_login_response_absolute_expiry() -> None:
    token, exp = RadixAuthManager._parse_login_response(
        {"jwt": "t", "expiresAt": "2999-01-01T00:00:00Z"}
    )
    assert token == "t"
    assert exp > time.time()


def test_parse_login_response_no_token_raises() -> None:
    with pytest.raises(RadixAuthError):
        RadixAuthManager._parse_login_response({"nope": 1})


def test_validity_window(tmp_path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr._is_valid() is False
    mgr._token = "t"
    mgr._expires_at = time.time() + 3600
    assert mgr._is_valid() is True
    # within the refresh margin -> considered invalid
    mgr._expires_at = time.time() + 30
    assert mgr._is_valid() is False


@pytest.mark.asyncio
async def test_get_token_refreshes_once_and_caches(tmp_path, monkeypatch) -> None:
    mgr = _mgr(tmp_path)
    calls = {"n": 0}

    async def fake_login() -> None:
        calls["n"] += 1
        mgr._token = f"token-{calls['n']}"
        mgr._expires_at = time.time() + 3600
        mgr._save_cache()

    monkeypatch.setattr(mgr, "_login", fake_login)

    t1 = await mgr.get_token()
    t2 = await mgr.get_token()  # still valid -> no second login
    assert t1 == t2 == "token-1"
    assert calls["n"] == 1
    assert mgr.cache_path.exists()

    # A fresh manager loads the cached token without logging in.
    mgr2 = _mgr(tmp_path)
    assert mgr2._is_valid() is True
    assert mgr2._token == "token-1"
