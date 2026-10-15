"""Compatibility shim for alternate import styles used by tests."""

try:
    from services.notes_provider import *  # noqa: F401,F403
except ImportError:  # pragma: no cover
    from notes_provider import *  # noqa: F401,F403
