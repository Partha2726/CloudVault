"""Intelligent Storage Optimization: CloudVault's heuristic (doc 07).

[APP] This is CloudVault's own rule set over application-recorded access logs. It is not an
AWS algorithm and not S3 Intelligent-Tiering. `evaluate` is pure: no I/O, no clock reads;
the caller loads access counts and passes `now`.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.config import REPO_DIR, Settings

STANDARD = "STANDARD"
STANDARD_IA = "STANDARD_IA"
GLACIER_IR = "GLACIER_IR"
SUPPORTED_CLASSES = frozenset({STANDARD, STANDARD_IA, GLACIER_IR})
COLD_CLASSES = frozenset({STANDARD_IA, GLACIER_IR})

# KEEP outcomes (doc 07.3) and recommendation rules (doc 07.4).
UNSUPPORTED_CLASS = "UNSUPPORTED_CLASS"
SMALL_OBJECT = "SMALL_OBJECT"
TOO_NEW = "TOO_NEW"
COOLDOWN = "COOLDOWN"
ACTIVE_USE = "ACTIVE_USE"
R1_PROMOTE = "R1_PROMOTE"
R2_TO_GIR = "R2_TO_GIR"
R3_TO_IA = "R3_TO_IA"


@dataclass(frozen=True)
class EngineConfig:
    """Thresholds (doc 07.2). IA_MIN_IDLE is defined as equal to MIN_AGE_IA."""

    min_size: int = 131_072
    min_age_ia_days: int = 30
    ia_max_accesses_90d: int = 2
    gir_min_age_days: int = 90
    promote_accesses_30d: int = 3
    cooldown_days: int = 30

    @property
    def ia_min_idle_days(self) -> int:
        return self.min_age_ia_days

    @classmethod
    def from_settings(cls, settings: Settings) -> "EngineConfig":
        return cls(
            min_size=settings.rec_min_size,
            min_age_ia_days=settings.rec_min_age_ia_days,
            ia_max_accesses_90d=settings.rec_ia_max_accesses_90d,
            gir_min_age_days=settings.rec_gir_min_age_days,
            promote_accesses_30d=settings.rec_promote_accesses_30d,
            cooldown_days=settings.rec_cooldown_days,
        )


@dataclass(frozen=True)
class VersionInputs:
    """Doc 07.1 inputs for the current version of an ACTIVE document."""

    size_bytes: int
    storage_class: str
    created_at: datetime
    storage_class_changed_at: datetime
    a30: int
    a90: int
    last_access: datetime | None


@dataclass(frozen=True)
class Result:
    kind: Literal["KEEP", "RECOMMEND"]
    rule_id: str  # KEEP code (e.g. TOO_NEW) or rule (e.g. R3_TO_IA)
    target: str | None  # recommended class; None for KEEP
    reason: str  # human-readable text for RECOMMEND; the KEEP code otherwise
    signals: dict[str, int]

    @property
    def is_recommendation(self) -> bool:
        return self.kind == "RECOMMEND"


def days_between(later: datetime, earlier: datetime) -> int:
    """Whole days elapsed (floor). `days()` in the doc 07.4 pseudocode."""
    return (later - earlier).days


def build_signals(v: VersionInputs, now: datetime) -> dict[str, int]:
    """Signals stored with a recommendation; keys match the doc 05.4 Recommendation shape."""
    last_seen = max(v.last_access or v.created_at, v.created_at)
    return {
        "size_bytes": v.size_bytes,
        "age_days": days_between(now, v.created_at),
        "a30": v.a30,
        "a90": v.a90,
        "idle_days": days_between(now, last_seen),
        "days_in_class": days_between(now, v.storage_class_changed_at),
    }


def _keep(code: str, signals: dict[str, int]) -> Result:
    return Result(kind="KEEP", rule_id=code, target=None, reason=code, signals=signals)


def _recommend(target: str, rule_id: str, reason: str, signals: dict[str, int]) -> Result:
    return Result(kind="RECOMMEND", rule_id=rule_id, target=target, reason=reason, signals=signals)


def evaluate(v: VersionInputs, now: datetime, cfg: EngineConfig) -> Result:
    """Doc 07.4: four KEEP guards in order, then R1, R2, R3 (first match wins)."""
    s = build_signals(v, now)
    cls = v.storage_class

    if cls not in SUPPORTED_CLASSES:
        return _keep(UNSUPPORTED_CLASS, s)
    if v.size_bytes < cfg.min_size:
        return _keep(SMALL_OBJECT, s)
    if s["age_days"] < cfg.min_age_ia_days:
        return _keep(TOO_NEW, s)
    if s["days_in_class"] < cfg.cooldown_days:
        return _keep(COOLDOWN, s)

    if cls in COLD_CLASSES and s["a30"] >= cfg.promote_accesses_30d:
        return _recommend(
            STANDARD,
            R1_PROMOTE,
            f"Accessed {s['a30']} times in 30 days; retrieval charges likely outweigh storage savings",
            s,
        )
    if cls in (STANDARD, STANDARD_IA) and s["age_days"] >= cfg.gir_min_age_days and s["a90"] == 0:
        return _recommend(GLACIER_IR, R2_TO_GIR, "Not accessed in 90 days and older than 90 days", s)
    if cls == STANDARD and s["a90"] <= cfg.ia_max_accesses_90d and s["idle_days"] >= cfg.ia_min_idle_days:
        return _recommend(
            STANDARD_IA,
            R3_TO_IA,
            f"Low access frequency ({s['a90']} in 90 days), idle {s['idle_days']} days",
            s,
        )
    return _keep(ACTIVE_USE, s)


# ---- optional pricing file (doc 07.5, Tier 3) ----

PRICING_REQUIRED_KEYS = ("region", "verified_on", "source_url", "storage_gb_month")


class PricingFileError(ValueError):
    pass


def load_pricing(path: str | None) -> dict[str, Any] | None:
    """Return the developer-filled pricing data, or None when no file is configured or present.

    Relative paths resolve from the repo root (where `.env` lives). A present but invalid
    file raises PricingFileError, so a typo never silently yields wrong numbers.
    How an estimate is shown is decided with the Optimization UI (T14/T23); until then the
    API's `estimate` stays null.
    """
    if not path:
        return None
    file = Path(path)
    if not file.is_absolute():
        file = REPO_DIR / file
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PricingFileError(f"Cannot read pricing file {file}: {exc}") from exc
    missing = [k for k in PRICING_REQUIRED_KEYS if k not in data]
    if missing:
        raise PricingFileError(f"Pricing file {file} is missing keys: {', '.join(missing)}")
    prices = data["storage_gb_month"]
    if not isinstance(prices, dict) or not SUPPORTED_CLASSES <= prices.keys():
        raise PricingFileError(f"Pricing file {file} needs storage_gb_month prices for {sorted(SUPPORTED_CLASSES)}")
    if not all(isinstance(prices[c], int | float) and prices[c] >= 0 for c in SUPPORTED_CLASSES):
        raise PricingFileError(f"Pricing file {file} has a non-numeric or negative price")
    return data
