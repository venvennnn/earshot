"""Environment configuration, validated once at startup.

Values come from environment variables or a `.env` file in the repo root or
`backend/`. Secrets are never logged: only the *names* of missing settings are.
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("earshot.config")

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Agora
    agora_app_id: str = ""
    agora_app_certificate: SecretStr = SecretStr("")
    # Agora REST gateway region nearest to the backend.
    agora_area: Literal["US", "EU", "AP"] = "US"

    # Public HTTPS URL that Agora's cloud can reach (Railway domain, or ngrok/cloudflared in dev)
    public_backend_url: str = ""

    # LLM: any OpenAI-compatible provider. Defaults target Gemini's OpenAI endpoint.
    llm_base_url: str = GEMINI_OPENAI_BASE_URL
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "gemini-3.8-flash"
    embedding_model: str = "gemini-embedding-001"
    # Lower reasoning keeps voice replies fast. Empty string = don't send the parameter.
    llm_reasoning_effort: str = "low"

    # Shared secret Agora sends to our custom LLM endpoint. Generated per process when unset.
    agent_llm_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(32)))

    # Murf
    murf_api_key: SecretStr = SecretStr("")
    murf_region_url: str = "https://global.api.murf.ai"
    # Optional: pin the agent's Murf voice (e.g. "en-IN-aarav"). Otherwise picked from Murf's voice list.
    murf_agent_voice: str = ""

    # MCP enterprise tool server
    mcp_enterprise_url: str = "http://localhost:8101/mcp"

    # Browser origins allowed to call the API (comma-separated). Add your Vercel domain in production.
    cors_origins: str = "http://localhost:5173"

    demo_mode: bool = False

    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("public_backend_url", "llm_base_url", "murf_region_url", "mcp_enterprise_url")
    @classmethod
    def _url_shape(cls, v: str) -> str:
        v = v.strip()
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return v

    @field_validator("agent_llm_key")
    @classmethod
    def _generate_llm_key(cls, v: SecretStr) -> SecretStr:
        return v if v.get_secret_value() else SecretStr(secrets.token_urlsafe(32))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    def integrations(self) -> dict[str, bool]:
        """Which integrations have the settings they need (booleans only, never values)."""
        return {
            "agora": bool(self.agora_app_id and self.agora_app_certificate.get_secret_value()),
            "public_url": self.public_backend_url.startswith("https://"),
            "llm": bool(self.llm_api_key.get_secret_value() and self.llm_model),
            "murf": bool(self.murf_api_key.get_secret_value()),
        }

    def missing(self) -> list[str]:
        """Names of env vars the live voice path still needs. Empty in DEMO_MODE except the LLM."""
        checks: dict[str, bool] = {
            "LLM_API_KEY": bool(self.llm_api_key.get_secret_value()),
        }
        if not self.demo_mode:
            checks |= {
                "AGORA_APP_ID": bool(self.agora_app_id),
                "AGORA_APP_CERTIFICATE": bool(self.agora_app_certificate.get_secret_value()),
                "PUBLIC_BACKEND_URL (https)": self.public_backend_url.startswith("https://"),
                "MURF_API_KEY": bool(self.murf_api_key.get_secret_value()),
            }
        return [name for name, ok in checks.items() if not ok]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def report_startup(settings: Settings) -> None:
    missing = settings.missing()
    mode = "DEMO_MODE (no external voice)" if settings.demo_mode else "live voice"
    if missing:
        log.warning(
            "EarShot starting in %s mode with missing settings: %s. "
            "Copy .env.example to .env and fill these in; features that need them will return a clear error.",
            mode,
            ", ".join(missing),
        )
    else:
        log.info("EarShot starting in %s mode; all required settings present.", mode)
