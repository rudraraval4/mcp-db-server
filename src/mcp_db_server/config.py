"""Runtime configuration for the MCP DB server.

All safety knobs live here so the security posture is configurable but has
safe defaults. Values are read from environment variables (prefix ``MCP_DB_``)
so an MCP client config can set them without code changes.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_DB_", env_file=".env", extra="ignore")

    # Connection -------------------------------------------------------------
    database_url: str = Field(
        default="sqlite:///./demo.db",
        description="SQLAlchemy URL. SQLite and PostgreSQL are supported.",
    )

    # Safety caps ------------------------------------------------------------
    max_rows: int = Field(default=1000, ge=1, description="Hard cap on rows returned.")
    statement_timeout_seconds: int = Field(
        default=10, ge=1, description="Abort queries running longer than this."
    )

    # Table access control ---------------------------------------------------
    allowed_tables: list[str] = Field(
        default_factory=list,
        description="If non-empty, ONLY these tables may be queried (allow-list).",
    )
    denied_tables: list[str] = Field(
        default_factory=list,
        description="These tables may never be queried (deny-list, applied after allow-list).",
    )

    # Auditing ---------------------------------------------------------------
    audit_log_path: str = Field(
        default="audit.log", description="Append-only log of every query attempt."
    )


def load_settings() -> Settings:
    return Settings()
