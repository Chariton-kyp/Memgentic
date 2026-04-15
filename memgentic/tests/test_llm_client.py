"""Tests for LLM client."""

from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

from memgentic.processing.llm import LLMClient


class DummySchema(BaseModel):
    answer: str = ""


def _make_settings(**overrides):
    """Create a mock settings object."""
    s = MagicMock()
    s.enable_llm_processing = overrides.get("enable_llm", True)
    s.google_api_key = overrides.get("google_api_key")
    s.summarization_model = "gemini-2.0-flash-lite"
    return s


def _make_client_with_model():
    """Create an LLMClient with a mocked model injected."""
    settings = _make_settings(google_api_key=None)
    client = LLMClient(settings)
    mock_model = MagicMock()
    client._model = mock_model
    return client, mock_model


# ---------------------------------------------------------------------------
# _create_model / available
# ---------------------------------------------------------------------------


def test_unavailable_when_no_api_key():
    settings = _make_settings(google_api_key=None)
    client = LLMClient(settings)
    assert client.available is False


def test_unavailable_when_disabled():
    settings = _make_settings(enable_llm=False, google_api_key="sk-test")
    client = LLMClient(settings)
    assert client.available is False


def test_available_true_when_model_exists():
    """available returns True when a model is present."""
    client, _ = _make_client_with_model()
    assert client.available is True


@patch("memgentic.processing.llm.ChatGoogleGenerativeAI", create=True)
def test_create_model_google_success(mock_chat_cls):
    """_create_model initialises Google model when API key is set."""
    mock_chat_cls.return_value = MagicMock()
    settings = _make_settings(google_api_key="test-key")
    with patch.dict(
        "sys.modules", {"langchain_google_genai": MagicMock(ChatGoogleGenerativeAI=mock_chat_cls)}
    ):
        client = LLMClient(settings)
    assert client.available is True


def test_create_model_google_init_exception_handled():
    """_create_model catches exception when Google init fails and returns None."""
    settings = _make_settings(google_api_key="test-key")
    with patch.dict(
        "sys.modules",
        {
            "langchain_google_genai": MagicMock(
                ChatGoogleGenerativeAI=MagicMock(side_effect=RuntimeError("init failed"))
            )
        },
    ):
        client = LLMClient(settings)
    # Should gracefully fall back to None
    assert client.available is False


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


async def test_generate_returns_empty_when_unavailable():
    settings = _make_settings()
    client = LLMClient(settings)
    result = await client.generate("test prompt")
    assert result == ""


async def test_generate_success_with_content_attr():
    """generate() returns response.content when model succeeds."""
    client, mock_model = _make_client_with_model()
    response = MagicMock()
    response.content = "generated answer"
    mock_model.ainvoke = AsyncMock(return_value=response)

    result = await client.generate("test prompt")
    assert result == "generated answer"
    mock_model.ainvoke.assert_awaited_once_with("test prompt")


async def test_generate_success_without_content_attr():
    """generate() falls back to str(response) when no .content."""
    client, mock_model = _make_client_with_model()
    response = "plain string response"
    mock_model.ainvoke = AsyncMock(return_value=response)

    result = await client.generate("prompt")
    assert result == "plain string response"


async def test_generate_exception_returns_empty():
    """generate() returns '' when model raises."""
    client, mock_model = _make_client_with_model()
    mock_model.ainvoke = AsyncMock(side_effect=RuntimeError("API error"))

    result = await client.generate("prompt")
    assert result == ""


# ---------------------------------------------------------------------------
# generate_structured()
# ---------------------------------------------------------------------------


async def test_generate_structured_returns_none_when_unavailable():
    settings = _make_settings()
    client = LLMClient(settings)
    result = await client.generate_structured("test", DummySchema)
    assert result is None


async def test_generate_structured_success():
    """generate_structured() returns parsed Pydantic model."""
    client, mock_model = _make_client_with_model()
    expected = DummySchema(answer="42")
    structured_mock = MagicMock()
    structured_mock.ainvoke = AsyncMock(return_value=expected)
    mock_model.with_structured_output.return_value = structured_mock

    result = await client.generate_structured("what is the answer?", DummySchema)
    assert result == expected
    mock_model.with_structured_output.assert_called_once_with(DummySchema)
    structured_mock.ainvoke.assert_awaited_once_with("what is the answer?")


async def test_generate_structured_exception_returns_none():
    """generate_structured() returns None when model raises."""
    client, mock_model = _make_client_with_model()
    structured_mock = MagicMock()
    structured_mock.ainvoke = AsyncMock(side_effect=ValueError("parse error"))
    mock_model.with_structured_output.return_value = structured_mock

    result = await client.generate_structured("prompt", DummySchema)
    assert result is None
