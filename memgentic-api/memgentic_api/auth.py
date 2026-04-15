"""Optional API key authentication for local Memgentic instances.

When MEMGENTIC_API_KEY is set in the environment, all API requests must include
a matching X-API-Key header. When not set, the API is open (local mode).
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from memgentic.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> None:
    """Verify API key if MEMGENTIC_API_KEY is configured.

    If no API key is configured, all requests are allowed (local mode).
    If configured, requests must include a matching X-API-Key header.
    """
    if not settings.api_key:
        return  # No API key configured — local open mode

    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    if not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
