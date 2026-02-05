"""ClawdBot - LLM Colony Agent Framework."""

__version__ = "0.1.0"

from clawdbot.exceptions import (
    BackendError,
    BudgetExceededError,
    ModelNotFoundError,
    MoltNetError,
    RegistryError,
)
from clawdbot.llm_registry import LLMRegistry, ModelSpec
from clawdbot.bot import Bot, BotState, BotGenome
from clawdbot.openclaw_bot import OpenClawBot, OpenClawBotState
from clawdbot.conversation_logger import ConversationLogger, create_conversation_logger
from clawdbot.reflection import (
    ReflectionContext,
    build_reflection_prompt,
    REFLECTION_PROMPTS,
)

__all__ = [
    # Core
    "LLMRegistry",
    "ModelSpec",
    # Exceptions
    "MoltNetError",
    "RegistryError",
    "ModelNotFoundError",
    "BackendError",
    "BudgetExceededError",
    # Bots
    "Bot",
    "BotState",
    "BotGenome",
    "OpenClawBot",
    "OpenClawBotState",
    # Conversation & Reflection
    "ConversationLogger",
    "create_conversation_logger",
    "ReflectionContext",
    "build_reflection_prompt",
    "REFLECTION_PROMPTS",
]
