"""
Multi-Model LLM Service

Provides a unified interface for multiple AI model providers.
Supports automatic fallback and model selection based on task type.

Supported Providers:
- OpenAI (GPT-4o, GPT-4o-mini)
- Anthropic (Claude 3.5 Sonnet)
- Google (Gemini 2.0)

Features:
- Unified chat completion API
- Automatic fallback on failure
- Cost tracking
- Model selection by task type
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, AsyncGenerator

from app.utils.datetime_utils import utc_now

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================================================
# Enums and Types
# =============================================================================

class ModelProvider(str, Enum):
    """Supported AI providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class TaskType(str, Enum):
    """Task types for model selection."""
    CHAT = "chat"  # General conversation
    ANALYSIS = "analysis"  # Data analysis, reasoning
    CREATIVE = "creative"  # Content generation
    CODE = "code"  # Code generation/analysis
    FAST = "fast"  # Quick responses, low latency


@dataclass
class ModelConfig:
    """Configuration for a model."""
    provider: ModelProvider
    model_id: str
    display_name: str
    max_tokens: int
    context_window: int
    cost_per_1k_input: float  # USD
    cost_per_1k_output: float
    supports_json_mode: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False


@dataclass
class ChatMessage:
    """A chat message."""
    role: str  # system, user, assistant
    content: str
    name: Optional[str] = None


@dataclass
class ChatCompletion:
    """Result from chat completion."""
    content: str
    model: str
    provider: ModelProvider
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    finish_reason: str = "stop"


# =============================================================================
# Model Configurations
# =============================================================================

AVAILABLE_MODELS: dict[str, ModelConfig] = {
    # OpenAI Models
    "gpt-4o": ModelConfig(
        provider=ModelProvider.OPENAI,
        model_id="gpt-4o",
        display_name="GPT-4o",
        max_tokens=4096,
        context_window=128000,
        cost_per_1k_input=0.005,
        cost_per_1k_output=0.015,
        supports_vision=True,
    ),
    "gpt-4o-mini": ModelConfig(
        provider=ModelProvider.OPENAI,
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        max_tokens=4096,
        context_window=128000,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        supports_vision=True,
    ),

    # Anthropic Models
    "claude-3-5-sonnet": ModelConfig(
        provider=ModelProvider.ANTHROPIC,
        model_id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        max_tokens=8192,
        context_window=200000,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        supports_vision=True,
    ),
    "claude-3-haiku": ModelConfig(
        provider=ModelProvider.ANTHROPIC,
        model_id="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        max_tokens=4096,
        context_window=200000,
        cost_per_1k_input=0.00025,
        cost_per_1k_output=0.00125,
        supports_vision=True,
    ),

    # Google Models
    "gemini-2.0-flash": ModelConfig(
        provider=ModelProvider.GOOGLE,
        model_id="gemini-2.0-flash-exp",
        display_name="Gemini 2.0 Flash",
        max_tokens=8192,
        context_window=1000000,
        cost_per_1k_input=0.0,  # Free tier
        cost_per_1k_output=0.0,
        supports_vision=True,
    ),
}

# Default models by task type
DEFAULT_MODELS: dict[TaskType, str] = {
    TaskType.CHAT: "gpt-4o",
    TaskType.ANALYSIS: "claude-3-5-sonnet",
    TaskType.CREATIVE: "gpt-4o",
    TaskType.CODE: "claude-3-5-sonnet",
    TaskType.FAST: "gpt-4o-mini",
}

# Fallback chain
FALLBACK_CHAIN = ["gpt-4o", "claude-3-5-sonnet", "gemini-2.0-flash", "gpt-4o-mini"]


# =============================================================================
# Provider Clients
# =============================================================================

class BaseProvider(ABC):
    """Base class for model providers."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> ChatCompletion:
        """Execute chat completion."""
        pass

    @abstractmethod
    async def stream_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion."""
        pass


class OpenAIProvider(BaseProvider):
    """OpenAI API provider."""

    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> ChatCompletion:
        start_time = utc_now()

        kwargs = {
            "model": model_config.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or model_config.max_tokens,
        }

        if json_mode and model_config.supports_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)

        latency = (utc_now() - start_time).total_seconds() * 1000

        usage = response.usage
        cost = (
            (usage.prompt_tokens / 1000 * model_config.cost_per_1k_input) +
            (usage.completion_tokens / 1000 * model_config.cost_per_1k_output)
        )

        return ChatCompletion(
            content=response.choices[0].message.content or "",
            model=model_config.model_id,
            provider=ModelProvider.OPENAI,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=cost,
            latency_ms=latency,
            finish_reason=response.choices[0].finish_reason,
        )

    async def stream_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        stream = await self.client.chat.completions.create(
            model=model_config.model_id,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AnthropicProvider(BaseProvider):
    """Anthropic API provider."""

    def __init__(self):
        try:
            from anthropic import AsyncAnthropic
            # Note: Requires ANTHROPIC_API_KEY env var
            self.client = AsyncAnthropic()
            self.available = True
        except Exception:
            self.client = None
            self.available = False

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> ChatCompletion:
        if not self.available:
            raise RuntimeError("Anthropic client not available")

        start_time = utc_now()

        # Separate system message
        system_msg = None
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        kwargs = {
            "model": model_config.model_id,
            "messages": chat_messages,
            "max_tokens": max_tokens or model_config.max_tokens,
        }

        if system_msg:
            kwargs["system"] = system_msg

        response = await self.client.messages.create(**kwargs)

        latency = (utc_now() - start_time).total_seconds() * 1000

        cost = (
            (response.usage.input_tokens / 1000 * model_config.cost_per_1k_input) +
            (response.usage.output_tokens / 1000 * model_config.cost_per_1k_output)
        )

        return ChatCompletion(
            content=response.content[0].text if response.content else "",
            model=model_config.model_id,
            provider=ModelProvider.ANTHROPIC,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            cost_usd=cost,
            latency_ms=latency,
            finish_reason=response.stop_reason or "stop",
        )

    async def stream_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not self.available:
            raise RuntimeError("Anthropic client not available")

        system_msg = None
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        kwargs = {
            "model": model_config.model_id,
            "messages": chat_messages,
            "max_tokens": model_config.max_tokens,
        }

        if system_msg:
            kwargs["system"] = system_msg

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


class GoogleProvider(BaseProvider):
    """Google Gemini API provider."""

    def __init__(self):
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.google_api_key)
            self.genai = genai
            self.available = True
        except Exception:
            self.genai = None
            self.available = False

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> ChatCompletion:
        if not self.available:
            raise RuntimeError("Google Gemini client not available")

        start_time = utc_now()

        model = self.genai.GenerativeModel(model_config.model_id)

        # Convert messages to Gemini format
        history = []
        for m in messages[:-1]:  # All but last
            role = "user" if m.role in ("user", "system") else "model"
            history.append({"role": role, "parts": [m.content]})

        chat = model.start_chat(history=history)

        # Send last message
        last_msg = messages[-1].content if messages else ""
        response = await chat.send_message_async(last_msg)

        latency = (utc_now() - start_time).total_seconds() * 1000

        # Estimate tokens (Gemini doesn't always return usage)
        input_tokens = sum(len(m.content.split()) * 1.3 for m in messages)
        output_tokens = len(response.text.split()) * 1.3

        return ChatCompletion(
            content=response.text,
            model=model_config.model_id,
            provider=ModelProvider.GOOGLE,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=int(input_tokens + output_tokens),
            cost_usd=0.0,  # Free tier
            latency_ms=latency,
        )

    async def stream_completion(
        self,
        messages: list[ChatMessage],
        model_config: ModelConfig,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not self.available:
            raise RuntimeError("Google Gemini client not available")

        model = self.genai.GenerativeModel(model_config.model_id)
        history = []
        for m in messages[:-1]:
            role = "user" if m.role in ("user", "system") else "model"
            history.append({"role": role, "parts": [m.content]})

        chat = model.start_chat(history=history)
        last_msg = messages[-1].content if messages else ""

        response = await chat.send_message_async(last_msg, stream=True)
        async for chunk in response:
            if chunk.text:
                yield chunk.text


# =============================================================================
# Unified LLM Service
# =============================================================================

class LLMService:
    """
    Unified interface for multiple LLM providers.

    Usage:
        llm = LLMService()
        result = await llm.chat([
            ChatMessage(role="user", content="Hello!")
        ])
    """

    def __init__(self):
        self.providers: dict[ModelProvider, BaseProvider] = {
            ModelProvider.OPENAI: OpenAIProvider(),
        }

        # Try to initialize optional providers
        try:
            anthropic = AnthropicProvider()
            if anthropic.available:
                self.providers[ModelProvider.ANTHROPIC] = anthropic
        except Exception:
            pass

        try:
            google = GoogleProvider()
            if google.available:
                self.providers[ModelProvider.GOOGLE] = google
        except Exception:
            pass

    def get_available_models(self) -> list[dict]:
        """Get list of available models."""
        available = []
        for model_id, config in AVAILABLE_MODELS.items():
            if config.provider in self.providers:
                available.append({
                    "id": model_id,
                    "name": config.display_name,
                    "provider": config.provider.value,
                    "context_window": config.context_window,
                    "supports_vision": config.supports_vision,
                })
        return available

    def get_model_for_task(self, task_type: TaskType) -> str:
        """Get recommended model for a task type."""
        preferred = DEFAULT_MODELS.get(task_type, "gpt-4o")

        # Check if preferred model is available
        config = AVAILABLE_MODELS.get(preferred)
        if config and config.provider in self.providers:
            return preferred

        # Find first available fallback
        for model_id in FALLBACK_CHAIN:
            config = AVAILABLE_MODELS.get(model_id)
            if config and config.provider in self.providers:
                return model_id

        return "gpt-4o"  # Default fallback

    async def chat(
        self,
        messages: list[ChatMessage],
        model: Optional[str] = None,
        task_type: Optional[TaskType] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        fallback: bool = True,
    ) -> ChatCompletion:
        """
        Execute chat completion.

        Args:
            messages: List of chat messages
            model: Specific model to use (optional)
            task_type: Task type for auto model selection
            temperature: Sampling temperature
            max_tokens: Max output tokens
            json_mode: Request JSON response
            fallback: Try fallback models on failure

        Returns:
            ChatCompletion result
        """
        # Select model
        if model:
            model_id = model
        elif task_type:
            model_id = self.get_model_for_task(task_type)
        else:
            model_id = "gpt-4o"

        # Build model list to try
        models_to_try = [model_id]
        if fallback:
            models_to_try.extend([m for m in FALLBACK_CHAIN if m != model_id])

        last_error = None

        for try_model in models_to_try:
            config = AVAILABLE_MODELS.get(try_model)
            if not config:
                continue

            provider = self.providers.get(config.provider)
            if not provider:
                continue

            try:
                return await provider.chat_completion(
                    messages=messages,
                    model_config=config,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except Exception as e:
                logger.warning(f"Model {try_model} failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All models failed. Last error: {last_error}")

    async def stream(
        self,
        messages: list[ChatMessage],
        model: Optional[str] = None,
        task_type: Optional[TaskType] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion.

        Yields text chunks as they're generated.
        """
        if model:
            model_id = model
        elif task_type:
            model_id = self.get_model_for_task(task_type)
        else:
            model_id = "gpt-4o"

        config = AVAILABLE_MODELS.get(model_id)
        if not config:
            raise ValueError(f"Unknown model: {model_id}")

        provider = self.providers.get(config.provider)
        if not provider:
            raise RuntimeError(f"Provider {config.provider} not available")

        async for chunk in provider.stream_completion(
            messages=messages,
            model_config=config,
            temperature=temperature,
        ):
            yield chunk


# =============================================================================
# Global Instance
# =============================================================================

_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get or create the LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
