import os
import unittest
from unittest.mock import MagicMock, patch

try:
    from services.groq_client import (
        GroqClient,
        GroqConfigurationError,
        GroqRequestError,
        GroqResponse,
    )
except ImportError:  # pragma: no cover
    from groq_client import (  # type: ignore
        GroqClient,
        GroqConfigurationError,
        GroqRequestError,
        GroqResponse,
    )


def make_completion(content="Hello from Groq", model="test-model", response_id="resp-1"):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    completion = MagicMock()
    completion.choices = [choice]
    completion.model = model
    completion.id = response_id
    return completion


class GroqClientTests(unittest.TestCase):
    def test_missing_api_key_raises_configuration_error(self):
        with self.assertRaises(GroqConfigurationError):
            GroqClient(environ={})

    def test_from_env_reads_configuration(self):
        environ = {
            "GROQ_API_KEY": "  secret-value  ",
            "GROQ_MODEL": "custom-model",
            "GROQ_TIMEOUT_SECONDS": "12.5",
            "GROQ_MAX_RETRIES": "4",
            "GROQ_TEMPERATURE": "0.7",
            "GROQ_MAX_TOKENS": "256",
            "GROQ_BASE_URL": "https://example.test",
        }
        client = GroqClient.from_env(environ=environ)
        self.assertEqual(client.config.api_key, "secret-value")
        self.assertEqual(client.config.model, "custom-model")
        self.assertEqual(client.config.timeout_seconds, 12.5)
        self.assertEqual(client.config.max_retries, 4)
        self.assertEqual(client.config.temperature, 0.7)
        self.assertEqual(client.config.max_tokens, 256)
        self.assertEqual(client.config.base_url, "https://example.test")
        self.assertEqual(client.config.redacted()["api_key"], "[redacted]")

    def test_invalid_environment_value_raises_configuration_error(self):
        with self.assertRaises(GroqConfigurationError):
            GroqClient.from_env(environ={"GROQ_API_KEY": "key", "GROQ_TIMEOUT_SECONDS": "not-a-number"})

    def test_chat_completion_uses_mocked_sdk_and_normalizes_response(self):
        with patch("services.groq_client.Groq") as mock_groq:
            sdk_client = MagicMock()
            mock_groq.return_value = sdk_client
            sdk_client.chat.completions.create.return_value = make_completion()

            client = GroqClient(api_key="test-key", model="env-model")
            response = client.chat_completion(
                [{"role": "user", "content": "Hi"}],
                temperature=0.1,
                max_tokens=64,
            )

            self.assertIsInstance(response, GroqResponse)
            self.assertEqual(response.content, "Hello from Groq")
            self.assertEqual(response.model, "test-model")
            self.assertEqual(response.response_id, "resp-1")
            self.assertEqual(response.finish_reason, "stop")

            mock_groq.assert_called_once()
            call_kwargs = mock_groq.call_args.kwargs
            self.assertEqual(call_kwargs["api_key"], "test-key")
            self.assertEqual(call_kwargs["max_retries"], 2)

            request_kwargs = sdk_client.chat.completions.create.call_args.kwargs
            self.assertEqual(request_kwargs["model"], "env-model")
            self.assertEqual(request_kwargs["messages"], [{"role": "user", "content": "Hi"}])
            self.assertEqual(request_kwargs["temperature"], 0.1)
            self.assertEqual(request_kwargs["max_tokens"], 64)
            self.assertEqual(request_kwargs["timeout"], 30.0)

    def test_complete_alias_returns_text(self):
        with patch("services.groq_client.Groq") as mock_groq:
            sdk_client = MagicMock()
            mock_groq.return_value = sdk_client
            sdk_client.chat.completions.create.return_value = make_completion(content="Alias works")

            client = GroqClient(api_key="test-key")
            text = client.complete([("user", "Hi")])

            self.assertEqual(text.content if hasattr(text, "content") else text, "Alias works")
            request_kwargs = sdk_client.chat.completions.create.call_args.kwargs
            self.assertEqual(request_kwargs["messages"], [{"role": "user", "content": "Hi"}])

    def test_generate_text_returns_string(self):
        with patch("services.groq_client.Groq") as mock_groq:
            sdk_client = MagicMock()
            mock_groq.return_value = sdk_client
            sdk_client.chat.completions.create.return_value = make_completion(content="Text only")

            client = GroqClient(api_key="test-key")
            self.assertEqual(client.generate_text([{"role": "user", "content": "Hi"}]), "Text only")

    def test_rate_limit_error_is_translated_safely(self):
        from groq import RateLimitError

        with patch("services.groq_client.Groq") as mock_groq:
            sdk_client = MagicMock()
            mock_groq.return_value = sdk_client
            sdk_client.chat.completions.create.side_effect = RateLimitError(
                "rate limited", response=MagicMock(), body=None
            )

            client = GroqClient(api_key="test-key")
            with self.assertRaises(GroqRequestError) as context:
                client.chat_completion([{"role": "user", "content": "Hi"}])

            self.assertIn("rate limit", str(context.exception).lower())
            self.assertNotIn("test-key", str(context.exception))

    def test_message_validation_errors(self):
        client = GroqClient(api_key="test-key")
        with self.assertRaises(GroqConfigurationError):
            client.chat_completion([])
        with self.assertRaises(GroqConfigurationError):
            client.chat_completion([{"role": "user"}])

    def test_no_completion_call_on_construction(self):
        with patch("services.groq_client.Groq") as mock_groq:
            GroqClient(api_key="test-key")
            mock_groq.assert_not_called()


if __name__ == "__main__":
    unittest.main()
