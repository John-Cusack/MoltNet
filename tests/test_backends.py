"""Tests for LLM backends."""

import pytest

from clawdbot.backends.base import LLMResponse, Message
from clawdbot.backends.ollama import OllamaBackend
from clawdbot.backends.anthropic import AnthropicBackend
from clawdbot.backends.openai_compatible import OpenAICompatibleBackend


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_total_tokens(self):
        """Test total token calculation."""
        response = LLMResponse(
            content="Hello",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            model="test-model",
            latency_ms=100.0,
        )
        assert response.total_tokens == 150


class TestMessage:
    """Tests for Message dataclass."""

    def test_message_creation(self):
        """Test creating messages."""
        user_msg = Message(role="user", content="Hello")
        assert user_msg.role == "user"
        assert user_msg.content == "Hello"

        system_msg = Message(role="system", content="You are helpful")
        assert system_msg.role == "system"


class TestOllamaBackend:
    """Tests for OllamaBackend."""

    def test_init_defaults(self):
        """Test default initialization."""
        backend = OllamaBackend(model_id="phi4-mini")
        assert backend.model_id == "phi4-mini"
        assert backend.base_url == "http://localhost:11434"
        assert backend.cost_per_1k_input == 0.0
        assert backend.cost_per_1k_output == 0.0

    def test_init_custom_url(self):
        """Test custom URL initialization."""
        backend = OllamaBackend(
            model_id="llama3.2",
            base_url="http://gpu-server:11434",
        )
        assert backend.base_url == "http://gpu-server:11434"

    def test_calculate_cost(self):
        """Test that Ollama cost is always zero."""
        backend = OllamaBackend(model_id="phi4-mini")
        cost = backend.calculate_cost(1000, 500)
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_health_check_connection_refused(self):
        """Test health check when Ollama is not running."""
        backend = OllamaBackend(
            model_id="phi4-mini",
            base_url="http://localhost:99999",  # Invalid port
        )
        result = await backend.health_check()
        assert result is False
        await backend.close()


class TestAnthropicBackend:
    """Tests for AnthropicBackend."""

    def test_init(self):
        """Test initialization."""
        backend = AnthropicBackend(
            model_id="claude-sonnet-4-5-20250514",
            api_key="test-key",
        )
        assert backend.model_id == "claude-sonnet-4-5-20250514"
        assert backend.base_url == "https://api.anthropic.com"
        assert backend.api_key == "test-key"

    def test_custom_costs(self):
        """Test custom cost configuration."""
        backend = AnthropicBackend(
            model_id="claude-3-5-haiku-20241022",
            api_key="test-key",
            cost_per_1k_input=0.0008,
            cost_per_1k_output=0.004,
        )
        cost = backend.calculate_cost(1000, 500)
        # 1000 * 0.0008/1000 + 500 * 0.004/1000 = 0.0008 + 0.002 = 0.0028
        assert cost == pytest.approx(0.0028)


class TestOpenAICompatibleBackend:
    """Tests for OpenAICompatibleBackend."""

    def test_init_openai(self):
        """Test OpenAI initialization."""
        backend = OpenAICompatibleBackend(
            model_id="gpt-4o",
            api_key="sk-test-key",
        )
        assert backend.model_id == "gpt-4o"
        assert backend.base_url == "https://api.openai.com/v1"

    def test_init_deepseek(self):
        """Test DeepSeek initialization."""
        backend = OpenAICompatibleBackend(
            model_id="deepseek-chat",
            api_key="ds-test-key",
            base_url="https://api.deepseek.com/v1",
            cost_per_1k_input=0.00014,
            cost_per_1k_output=0.00028,
        )
        assert backend.base_url == "https://api.deepseek.com/v1"
        cost = backend.calculate_cost(10000, 5000)
        # 10000 * 0.00014/1000 + 5000 * 0.00028/1000 = 0.0014 + 0.0014 = 0.0028
        assert cost == pytest.approx(0.0028)

    def test_init_mistral(self):
        """Test Mistral initialization."""
        backend = OpenAICompatibleBackend(
            model_id="mistral-large-latest",
            api_key="mistral-test-key",
            base_url="https://api.mistral.ai/v1",
        )
        assert backend.base_url == "https://api.mistral.ai/v1"

    def test_repr(self):
        """Test string representation."""
        backend = OpenAICompatibleBackend(
            model_id="gpt-4o",
            api_key="test",
        )
        repr_str = repr(backend)
        assert "OpenAICompatibleBackend" in repr_str
        assert "gpt-4o" in repr_str


# Integration tests - only run if Ollama is available
@pytest.mark.asyncio
async def test_ollama_integration():
    """Integration test for Ollama backend.

    Only runs if Ollama is available locally.
    """
    backend = OllamaBackend(model_id="phi4-mini")

    # Check if Ollama is running
    if not await backend.health_check():
        pytest.skip("Ollama not available or phi4-mini not loaded")

    try:
        response = await backend.generate(
            prompt="What is 2+2? Answer with just the number.",
            max_tokens=10,
            temperature=0.0,
        )
        assert response.content
        assert "4" in response.content
        assert response.cost_usd == 0.0
        assert response.model == "phi4-mini"
        assert response.latency_ms > 0
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_ollama_chat_integration():
    """Integration test for Ollama chat endpoint."""
    backend = OllamaBackend(model_id="phi4-mini")

    if not await backend.health_check():
        pytest.skip("Ollama not available or phi4-mini not loaded")

    try:
        messages = [
            Message(role="system", content="You are a math tutor."),
            Message(role="user", content="What is 3*3?"),
        ]
        response = await backend.generate_chat(
            messages=messages,
            max_tokens=10,
            temperature=0.0,
        )
        assert response.content
        assert "9" in response.content
    finally:
        await backend.close()
