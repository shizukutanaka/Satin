"""
SatinConfig — configuration schema / validator.

Uses Pydantic v2 when available; falls back to a plain Python dataclass that
accepts arbitrary keyword arguments so ConfigValidator can call SatinConfig(**cfg)
without crashing in environments where Pydantic is not installed.
"""
from __future__ import annotations

try:
    from pydantic import BaseModel, field_validator

    class SatinConfig(BaseModel):
        model_config = {"extra": "allow"}

        version: str = "1.0.0"

        @field_validator("version")
        @classmethod
        def _version_str(cls, v: str) -> str:
            if not isinstance(v, str):
                raise ValueError("version must be a string")
            return v

except ImportError:
    # Pydantic not installed — provide a no-op container so the import works.
    class SatinConfig:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
