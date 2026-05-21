"""
RadixAuthManager — automatic Bearer-token lifecycle for the Radix API.

KRAI used a *static* `RADIX_BEARER_TOKEN`, which breaks after ~1h. This manager
logs in via `/api/authenticateApps/login/apps`, caches the token (in-memory and
on disk for cross-process sharing), and transparently refreshes it before it
expires. `asyncio.Lock` serialises concurrent refreshes so a burst of ETL tasks
triggers exactly one login.

    auth = RadixAuthManager.from_settings(get_settings())
    headers = await auth.auth_headers()   # always a valid Bearer token

CONTRACT CONFIRMED (2026-05-21): the login path, request field names and token/
expiry parsing below were verified against the live Infominds API — a JWT was
issued with a 1h lifetime and a follow-up read returned data. Re-run
`python scripts/radix_login_check.py` if the API ever changes; the `_TOKEN_KEYS`
/ `_EXPIRY_*_KEYS` tuples already tolerate several response shapes.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

from insights.core.config import Settings
from insights.core.logging import get_logger

logger = get_logger(__name__)

# --- API contract (verify against Infominds docs) ---------------------------
_LOGIN_PATH = "/api/authenticateApps/login/apps"
# Request body field names -> we send camelCase keys.
_REQ_USERNAME = "userName"
_REQ_PASSWORD = "password"        # value is the base64-encoded password
_REQ_CLIENT_CODE = "clientCode"
_REQ_LICENSE_ID = "licenseId"
# Response: token may arrive under any of these keys.
_TOKEN_KEYS = ("token", "accessToken", "access_token", "bearerToken", "jwt")
# Response: lifetime in seconds may arrive under any of these keys.
_EXPIRY_SECONDS_KEYS = ("expiresIn", "expires_in", "expiresInSeconds", "lifetime")
# Response: absolute expiry timestamp may arrive under any of these keys.
_EXPIRY_AT_KEYS = ("expiresAt", "expiration", "expires_at", "validUntil")
_DEFAULT_LIFETIME_SECONDS = 3600  # ~1h fallback when the API omits an expiry


class RadixAuthError(RuntimeError):
    """Raised when authentication with Radix fails or is misconfigured."""


class RadixAuthManager:
    """Manages Radix Bearer-token acquisition, caching, and refresh."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password_base64: str,
        client_code: str,
        license_id: str,
        language: str = "DE",
        cache_path: str | Path = ".cache/radix_token.json",
        refresh_margin_seconds: int = 60,
    ) -> None:
        if not all([username, password_base64, client_code, license_id]):
            raise RadixAuthError(
                "Radix credentials incomplete: RADIX_USERNAME, RADIX_PASSWORD_BASE64, "
                "RADIX_CLIENT_CODE and RADIX_LICENSE_ID are all required."
            )
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password_base64 = password_base64
        self._client_code = client_code
        self._license_id = license_id
        self.language = language
        self.cache_path = Path(cache_path)
        self.refresh_margin_seconds = refresh_margin_seconds

        self._token: str | None = None
        self._expires_at: float = 0.0  # epoch seconds
        self._lock = asyncio.Lock()
        self._load_cache()

    @classmethod
    def from_settings(cls, settings: Settings) -> RadixAuthManager:
        """Build a manager from application settings."""
        return cls(
            base_url=settings.radix_api_url,
            username=settings.radix_username,
            password_base64=settings.radix_password_base64,
            client_code=settings.radix_client_code,
            license_id=settings.radix_license_id,
            language=settings.radix_api_language,
            cache_path=settings.radix_token_cache_path,
            refresh_margin_seconds=settings.radix_token_refresh_margin_seconds,
        )

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------
    async def get_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid Bearer token, refreshing if needed."""
        if not force_refresh and self._is_valid():
            return self._token  # type: ignore[return-value]

        async with self._lock:
            # Re-check inside the lock: another task may have just refreshed.
            if not force_refresh and self._is_valid():
                return self._token  # type: ignore[return-value]
            await self._login()
            return self._token  # type: ignore[return-value]

    async def auth_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        """Return request headers with a valid Bearer token."""
        token = await self.get_token(force_refresh=force_refresh)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Language": self.language,
        }

    # ----------------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------------
    def _is_valid(self) -> bool:
        return bool(self._token) and time.time() < (self._expires_at - self.refresh_margin_seconds)

    async def _login(self) -> None:
        """Authenticate against Radix and store the resulting token."""
        url = f"{self.base_url}{_LOGIN_PATH}"
        payload = {
            _REQ_USERNAME: self._username,
            _REQ_PASSWORD: self._password_base64,
            _REQ_CLIENT_CODE: self._client_code,
            _REQ_LICENSE_ID: self._license_id,
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}

        logger.info("Authenticating with Radix at %s", url)
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        logger.error("Radix login failed %s: %s", resp.status, text[:500])
                        raise RadixAuthError(f"Radix login HTTP {resp.status}: {text[:200]}")
                    data = json.loads(text) if text else {}
            except aiohttp.ClientError as exc:
                raise RadixAuthError(f"Network error during Radix login: {exc}") from exc

        token, expires_at = self._parse_login_response(data)
        self._token = token
        self._expires_at = expires_at
        self._save_cache()
        logger.info(
            "Radix token acquired; valid until %s",
            datetime.fromtimestamp(expires_at).isoformat(timespec="seconds"),
        )

    @staticmethod
    def _parse_login_response(data: dict[str, Any]) -> tuple[str, float]:
        """Extract (token, absolute_expiry_epoch) from a login response."""
        if not isinstance(data, dict):
            raise RadixAuthError(f"Unexpected login response type: {type(data).__name__}")

        token = next((str(data[k]) for k in _TOKEN_KEYS if data.get(k)), None)
        if not token:
            logger.error("No token in Radix response; keys=%s", sorted(data.keys()))
            raise RadixAuthError(
                f"No token field in Radix login response (keys: {sorted(data.keys())}). "
                "Adjust _TOKEN_KEYS in radix/auth.py to match the live API."
            )

        now = time.time()
        # Prefer relative lifetime (seconds), then absolute timestamp, then fallback.
        for key in _EXPIRY_SECONDS_KEYS:
            if data.get(key) is not None:
                try:
                    return token, now + float(data[key])
                except (TypeError, ValueError):
                    pass
        for key in _EXPIRY_AT_KEYS:
            if data.get(key):
                try:
                    iso = str(data[key]).replace("Z", "+00:00")
                    return token, datetime.fromisoformat(iso).timestamp()
                except ValueError:
                    pass
        logger.warning("No expiry in Radix response; assuming %ss lifetime.", _DEFAULT_LIFETIME_SECONDS)
        return token, now + _DEFAULT_LIFETIME_SECONDS

    def _load_cache(self) -> None:
        """Load a previously cached token (cross-process sharing)."""
        try:
            if self.cache_path.exists():
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._token = data.get("token")
                self._expires_at = float(data.get("expires_at", 0.0))
                if self._is_valid():
                    logger.debug("Loaded valid Radix token from cache %s", self.cache_path)
        except (OSError, ValueError) as exc:
            logger.warning("Could not read Radix token cache %s: %s", self.cache_path, exc)

    def _save_cache(self) -> None:
        """Persist the token so other processes can reuse it."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps({"token": self._token, "expires_at": self._expires_at}),
                encoding="utf-8",
            )
            # Best-effort: restrict permissions (no-op on Windows ACLs).
            try:
                self.cache_path.chmod(0o600)
            except OSError:
                pass
        except OSError as exc:
            logger.warning("Could not write Radix token cache %s: %s", self.cache_path, exc)
