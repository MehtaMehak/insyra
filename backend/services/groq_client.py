"""Reusable Groq client wrapper with environment-based configuration.

This module configures and safely calls the Groq SDK. It contains no mandatory
AI request: importing it or creating a client does not call Groq. Methods that
request completions are provided for later use and are fully testable by
mocking the SDK boundary.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # SDK is an optional runtime dependency behind the wrapper boundary.
    from groq import Groq as SDKGroq
    from groq import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        GroqError,
        RateLimitError,
    )
except ImportError:  # pragma: no cover - exercised only when SDK is absent.
    SDKGroq = None  # type: ignore[assignment]
    APIConnectionError = Exception  # type: ignore[assignment]
    APIStatusError = Exception  # type: ignore[assignment]
    APITimeoutError = Exception  # type: ignore[assignment]
    GroqError = Exception  # type: ignore[assignment]
    RateLimitError = Exception  # type: ignore[assignment]


Groq = SDKGroq


class GroqClientError(Exception):
    """Base error for all wrapper-level Groq failures."""


class GroqConfigurationError(GroqClientError):
    """Raised when required configuration is missing or invalid."""


class GroqRequestError(GroqClientError):
    """Raised when a Groq request fails safely."""


# Common defaults. They can be overridden with environment variables.
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_BASE_URL = "https://api.groq.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024


@dataclass(frozen=True)
class GroqConfig:
    """Immutable environment-backed Groq configuration."""

    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "GroqConfig":
        """Build configuration from environment variables.

        Missing API keys fail immediately. Other invalid values also fail
        explicitly rather than being silently coerced into unsafe behavior.
        """
        env = os.environ if environ is None else environ
        api_key = _clean_secret(env.get("GROQ_API_KEY", ""))
        if not api_key:
            raise GroqConfigurationError(
                "GROQ_API_KEY is required to create a Groq client."
            )

        model = _env_text(env, "GROQ_MODEL", DEFAULT_MODEL, allow_empty=False)
        base_url = _optional_env_text(env, "GROQ_BASE_URL")
        timeout_seconds = _env_float(
            env, "GROQ_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, minimum=0.1
        )
        max_retries = _env_int(env, "GROQ_MAX_RETRIES", DEFAULT_MAX_RETRIES, minimum=0)
        temperature = _env_float(env, "GROQ_TEMPERATURE", DEFAULT_TEMPERATURE, minimum=0.0)
        max_tokens = _env_int(env, "GROQ_MAX_TOKENS", DEFAULT_MAX_TOKENS, minimum=1)

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def redacted(self) -> dict[str, Any]:
        """A safe diagnostic dictionary that never includes the API key."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "api_key": "[redacted]",
        }


@dataclass
class GroqResponse:
    """Normalized response returned by the wrapper."""

    content: str
    model: str
    raw: Any = None
    response_id: str | None = None
    finish_reason: str | None = None


class GroqClient:
    """Reusable Groq client.

    The SDK object is created lazily and only when a request method is called.
    This keeps construction side-effect free and makes tests deterministic.
    """

    def __init__(
        self,
        config: GroqConfig | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        environ: Mapping[str, str] | None = None,
        sdk_factory: Callable[..., Any] | None = None,
        client: Any | None = None,
    ) -> None:
        if config is not None and (api_key is not None or model is not None or environ is not None):
            raise GroqConfigurationError("Pass either config or individual config overrides, not both.")

        if config is None:
            if api_key is None and environ is None and model is None:
                config = GroqConfig.from_env()
            else:
                merged = dict(os.environ if environ is None else environ)
                if api_key is not None:
                    merged["GROQ_API_KEY"] = api_key
                if model is not None:
                    merged["GROQ_MODEL"] = model
                config = GroqConfig.from_env(merged)

        self.config = config
        self._sdk_factory = sdk_factory or Groq
        self._client = client
        self._last_request_duration_seconds: float | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **kwargs: Any) -> "GroqClient":
        return cls(config=GroqConfig.from_env(environ), **kwargs)

    @property
    def model(self) -> str:
        return self.config.model

    def _sdk_client(self) -> Any:
        if self._client is not None:
            return self._client
        if SDKGroq is None:
            raise GroqConfigurationError(
                "The 'groq' package is not installed. Install it with: python -m pip install groq"
            )
        try:
            self._client = self._sdk_factory(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                max_retries=self.config.max_retries,
            )
        except Exception as exc:  # Defensive against SDK initialization failures.
            raise GroqConfigurationError(_safe_error_message("Unable to initialize Groq client", exc)) from None
        return self._client

    def chat_completion(
        self,
        messages: Sequence[Mapping[str, Any]] | Sequence[Any],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        response_format: Any | None = None,
        reasoning_effort: str | None = None,
    ) -> GroqResponse:
        """Send a chat-completion request and return normalized content."""
        normalized_messages = _normalize_messages(messages)
        selected_model = model or self.config.model
        selected_temperature = self.config.temperature if temperature is None else temperature
        selected_max_tokens = self.config.max_tokens if max_tokens is None else max_tokens
        selected_timeout = self.config.timeout_seconds if timeout is None else timeout

        client = self._sdk_client()
        request_started = time.monotonic()
        request_kwargs: dict[str, Any] = {
            "model": selected_model,
            "messages": normalized_messages,
            "temperature": selected_temperature,
            "max_tokens": selected_max_tokens,
            "timeout": selected_timeout,
        }
        if response_format is not None:
            request_kwargs["response_format"] = response_format
        if reasoning_effort is not None:
            request_kwargs["reasoning_effort"] = reasoning_effort

        try:
            completion = client.chat.completions.create(**request_kwargs)
        except RateLimitError as exc:
            raise GroqRequestError("Groq rate limit exceeded. Please retry later.") from None
        except APITimeoutError as exc:
            raise GroqRequestError("Groq request timed out.") from None
        except APIConnectionError as exc:
            raise GroqRequestError("Unable to connect to Groq.") from None
        except APIStatusError as exc:
            raise GroqRequestError(
                f"Groq request failed with HTTP status {getattr(exc, 'status_code', 'unknown')}."
            ) from None
        except GroqError as exc:
            raise GroqRequestError(_safe_error_message("Groq request failed", exc)) from None
        except Exception as exc:  # Last-resort safe handling for unexpected SDK errors.
            raise GroqRequestError(_safe_error_message("Groq request failed", exc)) from None
        finally:
            self._last_request_duration_seconds = time.monotonic() - request_started

        return _normalize_completion(completion, selected_model)

    # Convenience aliases for callers that use common completion names.
    complete = chat_completion
    generate = chat_completion
    create_chat_completion = chat_completion
    completion = chat_completion

    def generate_text(
        self,
        messages: Sequence[Mapping[str, Any]] | Sequence[Any],
        **kwargs: Any,
    ) -> str:
        """Return only the response text."""
        return self.chat_completion(messages, **kwargs).content

    @property
    def last_request_duration_seconds(self) -> float | None:
        return self._last_request_duration_seconds


def _clean_secret(value: str) -> str:
    return value.strip()


def _env_text(
    environ: Mapping[str, str],
    name: str,
    default: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = environ.get(name, default)
    if value is None:
        value = default
    value = value.strip()
    if not allow_empty and not value:
        raise GroqConfigurationError(f"{name} cannot be empty.")
    return value


def _optional_env_text(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int | None = None,
) -> int:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise GroqConfigurationError(f"{name} must be an integer.") from None
    if minimum is not None and value < minimum:
        raise GroqConfigurationError(f"{name} must be at least {minimum}.")
    return value


def _env_float(
    environ: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float | None = None,
) -> float:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise GroqConfigurationError(f"{name} must be a number.") from None
    if minimum is not None and value < minimum:
        raise GroqConfigurationError(f"{name} must be at least {minimum}.")
    return value


def _normalize_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, Mapping):
            if "role" not in message or "content" not in message:
                raise GroqConfigurationError("Each message must include 'role' and 'content'.")
            role = str(message["role"]).strip()
            content = message["content"]
            if not role:
                raise GroqConfigurationError("Message role cannot be empty.")
            normalized.append({"role": role, "content": content})
            continue

        if isinstance(message, (tuple, list)) and len(message) == 2:
            role, content = message
            role = str(role).strip()
            if not role:
                raise GroqConfigurationError("Message role cannot be empty.")
            normalized.append({"role": role, "content": content})
            continue

        raise GroqConfigurationError(
            "Messages must be mappings with role/content or (role, content) pairs."
        )

    if not normalized:
        raise GroqConfigurationError("At least one message is required.")
    return normalized


def _normalize_completion(completion: Any, model: str) -> GroqResponse:
    choices = getattr(completion, "choices", None)
    if not choices:
        raise GroqRequestError("Groq returned no choices.")

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if content is None:
        content = getattr(first_choice, "text", None)
    if content is None:
        content = ""
    if not isinstance(content, str):
        content = str(content)

    return GroqResponse(
        content=content,
        model=getattr(completion, "model", model) or model,
        raw=completion,
        response_id=getattr(completion, "id", None),
        finish_reason=getattr(first_choice, "finish_reason", None),
    )


def _safe_error_message(prefix: str, exc: Exception) -> str:
    """Return an error message without secrets or SDK internals."""
    name = type(exc).__name__
    text = str(exc)
    # Avoid carrying request payloads or credentials in user-facing errors.
    if len(text) > 300:
        text = text[:300] + "..."
    if not text:
        text = name
    return f"{prefix}: {name}: {text}"