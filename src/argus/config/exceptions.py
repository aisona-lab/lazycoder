from __future__ import annotations

from pathlib import Path


class ConfigLoadError(Exception):
    """Raised when a config file cannot be loaded or fails schema validation."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"Config validation failed for {path}: {message}")
