#!/usr/bin/env python3
"""Check Groq API key, model configuration, and connectivity.

This is a small diagnostic utility. It performs one minimal chat-completion
request and does not analyze reviews or store AI conclusions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_BACKEND = Path(__file__).resolve().parents[1]
if str(PROJECT_BACKEND) not in sys.path:
    sys.path.insert(0, str(PROJECT_BACKEND))

from services.groq_client import GroqClient, GroqClientError


def load_dotenv(path: Path) -> None:
    """Load a simple KEY=VALUE .env file into process environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_dotenv(PROJECT_BACKEND / ".env")

    try:
        client = GroqClient.from_env()
    except GroqClientError as exc:
        print(f"Groq configuration failed: {exc}", file=sys.stderr)
        return 1

    try:
        response = client.generate_text(
            [{"role": "user", "content": "Reply with the single word: OK"}],
            max_tokens=64,
            temperature=0.0,
        )
    except GroqClientError as exc:
        print(f"Groq connectivity failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # Defensive final boundary for CLI.
        print(f"Groq connectivity failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Groq connectivity OK")
    print(f"model: {client.model}")
    print(f"response: {response.strip() if isinstance(response, str) else response}")
    print(f"request_duration_seconds: {client.last_request_duration_seconds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
