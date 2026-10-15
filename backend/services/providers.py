"""Convenience re-exports for note and Gmail draft providers."""

from __future__ import annotations

try:
    from services.notes_provider import *
except ImportError:  # pragma: no cover
    from notes_provider import *  # type: ignore

try:
    from services.gmail_draft_provider import *
except ImportError:  # pragma: no cover
    from gmail_draft_provider import *  # type: ignore