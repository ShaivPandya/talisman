"""Run-domain errors mapped to HTTP status codes."""

from __future__ import annotations


class RunError(Exception):
    """User-facing run/replay/archive failure."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
