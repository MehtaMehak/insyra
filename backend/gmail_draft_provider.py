"""Compatibility shim for alternate import styles used by tests."""

try:
    from services.gmail_draft_provider import *  # noqa: F401,F403
except ImportError:  # pragma: no cover
    from gmail_draft_provider import *  # noqa: F401,F403
