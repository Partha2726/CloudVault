import pytest
from pydantic import ValidationError

from app.config import Settings

STRONG_A = "a" * 40
STRONG_B = "b" * 40
PROD = dict(
    app_env="production",
    jwt_secret=STRONG_A,
    sim_signing_secret=STRONG_B,
    database_url="postgresql+psycopg://u:p@neon.example/db?sslmode=require",
    public_api_base_url="https://cloudvault-api.example.com",
    frontend_origin="https://cloudvault.example.com",
)


def test_defaults_match_env_example(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    s = Settings(_env_file=None)
    assert (s.max_upload_bytes, s.presign_expiry_seconds, s.jwt_expire_minutes) == (10_485_760, 120, 60)
    assert (s.rec_min_size, s.rec_min_age_ia_days, s.rec_gir_min_age_days) == (131_072, 30, 90)
    assert (s.rec_ia_max_accesses_90d, s.rec_promote_accesses_30d, s.rec_cooldown_days) == (2, 3, 30)
    assert (s.storage_backend, s.sim_bucket_name) == ("postgres", "cloudvault-sim")
    assert s.sim_storage_limit_bytes == 314_572_800
    assert (s.processing_worker_enabled, s.max_process_bytes) == (True, 5_242_880)


def test_no_aws_settings_exist():
    assert not [name for name in Settings.model_fields if "aws" in name or "lambda" in name or "s3_bucket" in name]


def test_valid_production_settings_accepted():
    assert Settings(_env_file=None, **PROD).is_production


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"jwt_secret": "change-me-long-random"}, "JWT_SECRET"),
        ({"sim_signing_secret": "change-me-signing-secret"}, "SIM_SIGNING_SECRET"),
        ({"sim_signing_secret": "short"}, "SIM_SIGNING_SECRET"),
        ({"sim_signing_secret": STRONG_A}, "must differ"),
        ({"database_url": "postgresql+psycopg://u:p@neon.example/db"}, "sslmode=require"),
        ({"public_api_base_url": "http://cloudvault-api.example.com"}, "PUBLIC_API_BASE_URL must use https"),
        ({"frontend_origin": "http://cloudvault.example.com"}, "FRONTEND_ORIGIN must use https"),
    ],
)
def test_unsafe_production_settings_rejected(override, message):
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{**PROD, **override})


def test_development_allows_placeholders():
    assert not Settings(_env_file=None, app_env="development").is_production


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"sim_storage_limit_bytes": 1000}, "SIM_STORAGE_LIMIT_BYTES"),
        ({"presign_expiry_seconds": 0}, "PRESIGN_EXPIRY_SECONDS"),
        ({"processing_poll_seconds": 0}, "PROCESSING_POLL_SECONDS"),
        ({"storage_backend": "s3"}, "storage_backend"),
        ({"frontend_origin": "*"}, "FRONTEND_ORIGIN"),  # T24: CORS never becomes a wildcard
        ({"frontend_origin": ""}, "FRONTEND_ORIGIN"),
    ],
)
def test_invalid_ranges_rejected(override, message):
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **override)


def test_env_example_matches_settings():
    """Every variable in .env.example (except frontend/compose-only ones) is a known setting."""
    from dotenv import dotenv_values

    from app.config import REPO_DIR

    names = {k.lower() for k in dotenv_values(REPO_DIR / ".env.example")}
    assert names - {"vite_api_base_url"} <= set(Settings.model_fields)
