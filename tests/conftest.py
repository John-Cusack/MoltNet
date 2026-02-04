"""Pytest configuration and fixtures."""

import os
from pathlib import Path

import pytest

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Config paths
CONFIG_DIR = PROJECT_ROOT / "config"
LLM_REGISTRY_PATH = CONFIG_DIR / "llm-registry.yaml"


@pytest.fixture
def registry_path():
    """Path to the LLM registry config file."""
    return LLM_REGISTRY_PATH


@pytest.fixture
def temp_registry(tmp_path):
    """Create a temporary registry file for testing."""
    content = """
providers:
  test_local:
    name: "Test Local"
    base_url: "http://localhost:11434"
    auth_env: null
    api_format: "ollama"
  test_api:
    name: "Test API"
    base_url: "https://api.test.com"
    auth_env: "TEST_API_KEY"
    api_format: "openai_compatible"

models:
  test_local/model-a:
    display_name: "Test Model A"
    provider: test_local
    model_id: "model-a"
    context_window: 8192
    max_output_tokens: 2048
    cost_per_1k_input: 0.0
    cost_per_1k_output: 0.0
    quality_tier: 2
    strengths:
      - code
      - math
    weaknesses:
      - creative_writing
    notes: "A free test model"

  test_api/model-b:
    display_name: "Test Model B"
    provider: test_api
    model_id: "model-b"
    context_window: 32768
    max_output_tokens: 4096
    cost_per_1k_input: 0.001
    cost_per_1k_output: 0.002
    quality_tier: 3
    strengths:
      - code
      - reasoning
    weaknesses:
      - speed
    notes: "A paid test model"

  test_api/model-c:
    display_name: "Test Model C (Premium)"
    provider: test_api
    model_id: "model-c"
    context_window: 100000
    max_output_tokens: 8192
    cost_per_1k_input: 0.01
    cost_per_1k_output: 0.03
    quality_tier: 4
    strengths:
      - code
      - reasoning
      - creative_writing
    weaknesses: []
    notes: "Premium test model"

task_routing:
  code:
    best: ["test_api/model-c", "test_api/model-b"]
    budget: ["test_api/model-b", "test_local/model-a"]
    free: ["test_local/model-a"]
"""
    config_file = tmp_path / "test-registry.yaml"
    config_file.write_text(content)
    return config_file


@pytest.fixture
def mock_api_key(monkeypatch):
    """Set a mock API key for testing."""
    monkeypatch.setenv("TEST_API_KEY", "test-key-12345")
    return "test-key-12345"


@pytest.fixture
def clear_api_keys(monkeypatch):
    """Clear all API keys for testing unavailability."""
    for key in ["TEST_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
