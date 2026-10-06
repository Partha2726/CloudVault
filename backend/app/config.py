from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# Placeholder values from .env.example; never acceptable in production.
_PLACEHOLDER_SECRETS = {"change-me", "change-me-long-random", "change-me-signing-secret"}
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Settings from environment variables (doc 11.4 as amended by doc 15 AM-7: no AWS variables).

    Real environment variables win; otherwise `.env` at the repo root, then `backend/.env`.
    """

    model_config = SettingsConfigDict(env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://cloudvault:cloudvault@localhost:5432/cloudvault"
    jwt_secret: str = "change-me-long-random"
    jwt_expire_minutes: int = 60
    frontend_origin: str = "http://localhost:5173"
    max_upload_bytes: int = 10_485_760

    # Simulated S3 store (AM-7)
    storage_backend: Literal["postgres"] = "postgres"
    sim_bucket_name: str = "cloudvault-sim"
    sim_storage_limit_bytes: int = 314_572_800
    sim_signing_secret: str = "change-me-signing-secret"
    public_api_base_url: str = "http://localhost:8000"
    presign_expiry_seconds: int = 120

    # Processing worker (AM-7)
    processing_worker_enabled: bool = True
    processing_poll_seconds: float = 2.0
    max_process_bytes: int = 5_242_880

    rec_min_size: int = 131_072
    rec_min_age_ia_days: int = 30
    rec_gir_min_age_days: int = 90
    rec_ia_max_accesses_90d: int = 2
    rec_promote_accesses_30d: int = 3
    rec_cooldown_days: int = 30
    pricing_file: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _check_ranges(self) -> "Settings":
        if self.sim_storage_limit_bytes < self.max_upload_bytes:
            raise ValueError("SIM_STORAGE_LIMIT_BYTES must be at least MAX_UPLOAD_BYTES")
        if not 1 <= self.presign_expiry_seconds <= 3600:
            raise ValueError("PRESIGN_EXPIRY_SECONDS must be between 1 and 3600")
        if self.processing_poll_seconds <= 0:
            raise ValueError("PROCESSING_POLL_SECONDS must be positive")
        if self.frontend_origin.strip() in ("", "*"):  # CORS allows exactly this one origin (doc 09.1)
            raise ValueError("FRONTEND_ORIGIN must be one explicit origin, not '*'")
        return self

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        """Production rules (doc 11.4, AM-7): strong distinct secrets, TLS to the DB and the public API."""
        if not self.is_production:
            return self
        problems = []
        for name in ("jwt_secret", "sim_signing_secret"):
            value = getattr(self, name)
            if value in _PLACEHOLDER_SECRETS or len(value) < _MIN_SECRET_LENGTH:
                problems.append(f"{name.upper()} must be a random value of at least {_MIN_SECRET_LENGTH} characters")
        if self.jwt_secret == self.sim_signing_secret:
            problems.append("JWT_SECRET and SIM_SIGNING_SECRET must differ")
        if "sslmode=require" not in self.database_url:
            problems.append("DATABASE_URL must use sslmode=require")
        if not self.public_api_base_url.startswith("https://"):
            problems.append("PUBLIC_API_BASE_URL must use https")
        if not self.frontend_origin.startswith("https://"):
            problems.append("FRONTEND_ORIGIN must use https")
        if problems:
            raise ValueError("; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
