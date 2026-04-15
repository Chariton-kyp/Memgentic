"""Tests for security hardening: headers, request size limits, authentication."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from memgentic_api.main import RequestSizeLimitMiddleware, SecurityHeadersMiddleware


def _security_app() -> FastAPI:
    """Build a minimal FastAPI app with security middlewares for testing."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/echo")
    async def echo():
        return {"ok": True}

    return app


@pytest.fixture
async def sec_client():
    """Yield an httpx.AsyncClient wired to the security test app."""
    app = _security_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# --- Security Headers ---


async def test_security_headers_present(sec_client: AsyncClient):
    """All security headers are set on responses."""
    resp = await sec_client.get("/ping")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-XSS-Protection"] == "1; mode=block"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


async def test_security_headers_on_post(sec_client: AsyncClient):
    """Security headers are present on POST responses too."""
    resp = await sec_client.post("/echo")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


async def test_security_headers_on_404(sec_client: AsyncClient):
    """Security headers are present even on 404 responses."""
    resp = await sec_client.get("/nonexistent")
    assert resp.status_code == 404
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


# --- Request Size Limit ---


async def test_request_size_limit_rejects_oversized(sec_client: AsyncClient):
    """Requests with content-length exceeding 10MB are rejected with 413."""
    resp = await sec_client.post(
        "/echo",
        content=b"x",
        headers={"content-length": str(11 * 1024 * 1024)},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Request body too large"


async def test_request_size_limit_allows_normal(sec_client: AsyncClient):
    """Requests within the size limit are accepted."""
    resp = await sec_client.post(
        "/echo",
        content=b"small payload",
    )
    assert resp.status_code == 200


async def test_request_size_limit_allows_exactly_10mb(sec_client: AsyncClient):
    """Requests exactly at the 10MB boundary are accepted."""
    resp = await sec_client.post(
        "/echo",
        content=b"x",
        headers={"content-length": str(10 * 1024 * 1024)},
    )
    assert resp.status_code == 200


# --- Authentication ---


async def test_auth_verify_rejects_invalid_key():
    """verify_api_key raises 401 for invalid keys."""
    from fastapi import HTTPException

    from memgentic_api.auth import verify_api_key

    with patch("memgentic_api.auth.settings") as mock_settings:
        mock_settings.api_key = "correct-key-123"
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key("wrong-key")
        assert exc_info.value.status_code == 401


async def test_auth_verify_rejects_missing_key():
    """verify_api_key raises 401 when no key is provided but one is required."""
    from fastapi import HTTPException

    from memgentic_api.auth import verify_api_key

    with patch("memgentic_api.auth.settings") as mock_settings:
        mock_settings.api_key = "correct-key-123"
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(None)
        assert exc_info.value.status_code == 401


async def test_auth_allows_when_no_key_configured():
    """verify_api_key passes when no API key is configured (local mode)."""
    from memgentic_api.auth import verify_api_key

    with patch("memgentic_api.auth.settings") as mock_settings:
        mock_settings.api_key = ""
        result = await verify_api_key(None)
        assert result is None


async def test_auth_allows_valid_key():
    """verify_api_key accepts a correct key and returns None."""
    from memgentic_api.auth import verify_api_key

    with patch("memgentic_api.auth.settings") as mock_settings:
        mock_settings.api_key = "correct-key-123"
        result = await verify_api_key("correct-key-123")
        assert result is None
