"""
Radix login smoke test.

Verifies the Radix credentials in `.env`, exercises RadixAuthManager (login +
token cache), and reaches a read-only endpoint to confirm the API contract in
`insights/etl/radix/auth.py` against the live Infominds API.

    python scripts/radix_login_check.py

Read-only: only logs in and requests activity states. ASCII-only output so it
runs cleanly on the Windows console (cp1252).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from insights.core.config import get_settings  # noqa: E402
from insights.etl.radix import RadixAuthManager, RadixDataClient  # noqa: E402


async def main() -> int:
    settings = get_settings()
    if not settings.is_radix_configured:
        print("[FAIL] Radix credentials incomplete. Set RADIX_USERNAME / RADIX_PASSWORD_BASE64 / "
              "RADIX_CLIENT_CODE / RADIX_LICENSE_ID in .env.")
        return 1

    auth = RadixAuthManager.from_settings(settings)
    try:
        token = await auth.get_token(force_refresh=True)
    except Exception as exc:
        print(f"[FAIL] Login failed: {exc}")
        print("  If the error mentions missing token/expiry keys, adjust the _TOKEN_KEYS / "
              "_EXPIRY_*_KEYS constants in insights/etl/radix/auth.py to match the API.")
        return 1

    print(f"[OK] Token acquired (len={len(token)}). Cached at {auth.cache_path}")
    try:
        async with RadixDataClient(auth) as client:
            states = await client.get_activity_states()
        print(f"[OK] Reached Radix API - {len(states)} activity states returned.")
    except Exception as exc:
        print(f"[WARN] Token OK but data request failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
