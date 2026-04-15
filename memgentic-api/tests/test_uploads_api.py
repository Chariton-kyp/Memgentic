"""Tests for upload endpoints — text, file, URL."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

# --- Text uploads ---


async def test_upload_text(client: AsyncClient):
    """POST /api/v1/upload/text creates an upload record + memory."""
    payload = {
        "content": "This is my uploaded note about Kubernetes networking",
        "title": "Networking notes",
        "topics": ["kubernetes", "networking"],
        "content_type": "learning",
    }
    resp = await client.post("/api/v1/upload/text", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "Networking notes"
    assert data["status"] == "completed"
    assert data["memory_id"]  # memory was created

    # Follow-up: the memory exists
    mem_resp = await client.get(f"/api/v1/memories/{data['memory_id']}")
    assert mem_resp.status_code == 200
    assert "kubernetes" in mem_resp.json()["content"].lower()


async def test_upload_text_empty(client: AsyncClient):
    """POST /api/v1/upload/text with too-short content returns 422."""
    resp = await client.post("/api/v1/upload/text", json={"content": ""})
    assert resp.status_code == 422


async def test_upload_text_default_title(client: AsyncClient):
    """POST /api/v1/upload/text without a title uses 'Text upload'."""
    resp = await client.post(
        "/api/v1/upload/text",
        json={"content": "Short but valid text content for upload"},
    )
    assert resp.status_code == 201
    assert resp.json()["filename"] == "Text upload"


# --- File uploads ---


async def test_upload_file_txt(client: AsyncClient):
    """POST /api/v1/upload/file with a plain text file creates a memory."""
    file_content = b"This is a text file with useful content to remember."
    files = {"file": ("notes.txt", file_content, "text/plain")}
    resp = await client.post("/api/v1/upload/file", files=files)
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "notes.txt"
    assert data["status"] == "completed"
    assert data["memory_id"]

    # Verify memory exists
    mem_resp = await client.get(f"/api/v1/memories/{data['memory_id']}")
    assert mem_resp.status_code == 200
    assert "useful content" in mem_resp.json()["content"]


async def test_upload_file_markdown(client: AsyncClient):
    """POST /api/v1/upload/file with markdown works too."""
    md_content = b"# Title\n\nSome markdown content worth remembering."
    files = {"file": ("doc.md", md_content, "text/markdown")}
    resp = await client.post("/api/v1/upload/file", files=files)
    assert resp.status_code == 201
    assert resp.json()["status"] == "completed"


async def test_upload_file_unsupported_mime(client: AsyncClient):
    """POST /api/v1/upload/file with an unsupported mime returns 422."""
    files = {
        "file": (
            "image.png",
            b"fake png bytes",
            "image/png",
        )
    }
    resp = await client.post("/api/v1/upload/file", files=files)
    assert resp.status_code == 422


# --- URL uploads ---


async def test_upload_url_invalid_too_short(client: AsyncClient):
    """POST /api/v1/upload/url with a URL shorter than min_length returns 422."""
    resp = await client.post("/api/v1/upload/url", json={"url": "bad"})
    assert resp.status_code == 422


async def test_upload_url_fetch_failure(client: AsyncClient):
    """POST /api/v1/upload/url returns 422 when URL fetch fails."""

    async def _fake_extract(url: str):
        raise ValueError("Failed to fetch URL: connection refused")

    with patch(
        "memgentic.processing.file_ingest.extract_text_from_url",
        new=AsyncMock(side_effect=_fake_extract),
    ):
        resp = await client.post(
            "/api/v1/upload/url",
            json={"url": "http://nonexistent.invalid/page"},
        )
    assert resp.status_code == 422
    assert "Failed to fetch" in resp.json()["detail"]


async def test_upload_url_success(client: AsyncClient):
    """POST /api/v1/upload/url ingests extracted text into a memory."""

    async def _fake_extract(url: str):
        return (
            "Extracted page text about cryptography and zero-knowledge proofs.",
            "Cryptography Page",
        )

    with patch(
        "memgentic.processing.file_ingest.extract_text_from_url",
        new=AsyncMock(side_effect=_fake_extract),
    ):
        resp = await client.post(
            "/api/v1/upload/url",
            json={
                "url": "https://example.com/crypto-page",
                "topics": ["cryptography"],
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "completed"
    assert data["filename"] == "Cryptography Page"
    assert data["memory_id"]


# --- List uploads ---


async def test_list_uploads(client: AsyncClient):
    """GET /api/v1/uploads returns previously created uploads."""
    # Start with empty uploads
    empty_resp = await client.get("/api/v1/uploads")
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []

    # Create two text uploads
    await client.post(
        "/api/v1/upload/text",
        json={"content": "First upload content for list test"},
    )
    await client.post(
        "/api/v1/upload/text",
        json={"content": "Second upload content for list test"},
    )

    list_resp = await client.get("/api/v1/uploads")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert len(data) == 2
    for item in data:
        assert item["status"] == "completed"
        assert item["memory_id"]
