"""T13: doc 07 engine. U1-U8 (doc 10.2) plus boundaries for each threshold. Clock injected."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.services.recommendation_engine import (
    EngineConfig,
    PricingFileError,
    VersionInputs,
    evaluate,
    load_pricing,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CFG = EngineConfig()
MB = 1024 * 1024


def days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


def version(
    *, size=18 * MB, cls="STANDARD", age=120, in_class=None, a30=0, a90=0, idle=None
) -> VersionInputs:
    """Inputs for a version `age` days old; `idle` days since the last recorded access (None = never)."""
    return VersionInputs(
        size_bytes=size,
        storage_class=cls,
        created_at=days_ago(age),
        storage_class_changed_at=days_ago(age if in_class is None else in_class),
        a30=a30,
        a90=a90,
        last_access=None if idle is None else days_ago(idle),
    )


def outcome(v: VersionInputs, cfg: EngineConfig = CFG) -> tuple[str, str | None]:
    r = evaluate(v, NOW, cfg)
    return r.rule_id, r.target


# ---- doc 10.2 U1-U8 ----

def test_u1_r3_positive():
    r = evaluate(version(age=120, a30=0, a90=1, idle=40), NOW, CFG)
    assert (r.kind, r.rule_id, r.target) == ("RECOMMEND", "R3_TO_IA", "STANDARD_IA")
    assert r.reason == "Low access frequency (1 in 90 days), idle 40 days"
    assert r.signals == {
        "size_bytes": 18 * MB, "age_days": 120, "a30": 0, "a90": 1, "idle_days": 40, "days_in_class": 120,
    }


def test_u2_boundary_age():
    assert outcome(version(age=29, a90=0))[0] == "TOO_NEW"
    assert outcome(version(age=30, a90=0)) == ("R3_TO_IA", "STANDARD_IA")


def test_u3_small_file():
    assert outcome(version(size=100 * 1024, age=200)) == ("SMALL_OBJECT", None)


def test_u4_promote():
    r = evaluate(version(cls="STANDARD_IA", age=120, in_class=60, a30=4, a90=4, idle=1), NOW, CFG)
    assert (r.rule_id, r.target) == ("R1_PROMOTE", "STANDARD")
    assert r.reason == "Accessed 4 times in 30 days; retrieval charges likely outweigh storage savings"


def test_u5_cooldown():
    assert outcome(version(cls="STANDARD_IA", age=200, in_class=10, a30=5, a90=5, idle=1)) == ("COOLDOWN", None)


def test_u6_very_cold():
    r = evaluate(version(age=100, a90=0), NOW, CFG)
    assert (r.rule_id, r.target) == ("R2_TO_GIR", "GLACIER_IR")
    assert r.reason == "Not accessed in 90 days and older than 90 days"


def test_u7_unsupported_class():
    assert outcome(version(cls="DEEP_ARCHIVE")) == ("UNSUPPORTED_CLASS", None)


def test_u8_recently_accessed():
    r = evaluate(version(age=60, a30=1, a90=1, idle=5), NOW, CFG)
    assert (r.kind, r.rule_id, r.target) == ("KEEP", "ACTIVE_USE", None)


# ---- guard order and rule priority ----

def test_unsupported_class_checked_before_size():
    assert outcome(version(cls="GLACIER", size=1))[0] == "UNSUPPORTED_CLASS"


def test_small_checked_before_age():
    assert outcome(version(size=1, age=1))[0] == "SMALL_OBJECT"


def test_too_new_checked_before_cooldown():
    assert outcome(version(age=5, in_class=5))[0] == "TOO_NEW"


def test_r2_wins_over_r3_when_both_match():
    # STANDARD, 120 days, never accessed: qualifies for R2 and R3; R2 is checked first.
    assert outcome(version(age=120, a90=0)) == ("R2_TO_GIR", "GLACIER_IR")


def test_r1_wins_over_r2_for_cold_class():
    # Hypothetical counts (a30 > a90 cannot happen in real data) to exercise priority.
    assert outcome(version(cls="STANDARD_IA", age=200, in_class=100, a30=3, a90=0))[0] == "R1_PROMOTE"


def test_standard_ia_can_move_to_gir():
    assert outcome(version(cls="STANDARD_IA", age=200, in_class=100, a90=0)) == ("R2_TO_GIR", "GLACIER_IR")


def test_glacier_ir_never_gets_r2_or_r3():
    assert outcome(version(cls="GLACIER_IR", age=300, in_class=200, a90=0)) == ("ACTIVE_USE", None)


def test_standard_never_promoted():
    assert outcome(version(age=200, a30=10, a90=10, idle=0)) == ("ACTIVE_USE", None)


def test_standard_ia_with_few_accesses_kept():
    assert outcome(version(cls="STANDARD_IA", age=200, in_class=100, a30=2, a90=2, idle=3)) == ("ACTIVE_USE", None)


# ---- threshold boundaries ----

def test_min_size_boundary():
    assert outcome(version(size=CFG.min_size - 1, age=100))[0] == "SMALL_OBJECT"
    assert outcome(version(size=CFG.min_size, age=100))[0] == "R2_TO_GIR"


def test_cooldown_boundary():
    v = version(cls="STANDARD_IA", age=200, a30=3, a90=3, idle=1)
    assert outcome(replace(v, storage_class_changed_at=days_ago(29)))[0] == "COOLDOWN"
    assert outcome(replace(v, storage_class_changed_at=days_ago(30)))[0] == "R1_PROMOTE"


def test_promote_boundary():
    v = version(cls="GLACIER_IR", age=200, in_class=100, a90=5, idle=1)
    assert outcome(replace(v, a30=2))[0] == "ACTIVE_USE"
    assert outcome(replace(v, a30=3)) == ("R1_PROMOTE", "STANDARD")


def test_gir_age_boundary():
    assert outcome(version(age=89, a90=0))[0] == "R3_TO_IA"
    assert outcome(version(age=90, a90=0))[0] == "R2_TO_GIR"


def test_r2_requires_zero_accesses():
    assert outcome(version(age=120, a90=1, idle=80))[0] == "R3_TO_IA"


def test_ia_access_boundary():
    assert outcome(version(age=60, a90=2, idle=30))[0] == "R3_TO_IA"
    assert outcome(version(age=60, a90=3, idle=30))[0] == "ACTIVE_USE"


def test_idle_boundary():
    assert outcome(version(age=60, a90=1, idle=29))[0] == "ACTIVE_USE"
    assert outcome(version(age=60, a90=1, idle=30))[0] == "R3_TO_IA"


# ---- signals ----

def test_days_are_whole_days_floor():
    v = replace(version(age=0, a90=0), created_at=NOW - timedelta(days=29, hours=23, minutes=59))
    r = evaluate(v, NOW, CFG)
    assert r.signals["age_days"] == 29 and r.rule_id == "TOO_NEW"


def test_idle_counts_from_creation_when_never_accessed():
    assert evaluate(version(age=45, a90=0), NOW, CFG).signals["idle_days"] == 45


def test_idle_ignores_access_recorded_before_creation():
    # Seeded/backdated data could log an access earlier than created_at; doc 07.4 takes the later.
    v = replace(version(age=40), last_access=days_ago(100))
    assert evaluate(v, NOW, CFG).signals["idle_days"] == 40


# ---- properties ----

def test_deterministic_and_pure():
    v = version(age=120, a90=1, idle=40)
    assert evaluate(v, NOW, CFG) == evaluate(v, NOW, CFG)


def test_thresholds_come_from_settings():
    cfg = EngineConfig.from_settings(Settings(_env_file=None, rec_min_age_ia_days=10, rec_cooldown_days=5))
    assert (cfg.min_age_ia_days, cfg.ia_min_idle_days, cfg.cooldown_days) == (10, 10, 5)
    assert outcome(version(age=15, a90=0, idle=12), cfg) == ("R3_TO_IA", "STANDARD_IA")


def test_default_config_matches_settings_defaults():
    assert EngineConfig.from_settings(Settings(_env_file=None)) == EngineConfig()


# ---- pricing file (doc 07.5) ----

VALID_PRICING = {
    "region": "ap-south-1",
    "verified_on": "2026-10-05",
    "source_url": "https://aws.amazon.com/s3/pricing/",
    "storage_gb_month": {"STANDARD": 0.025, "STANDARD_IA": 0.0138, "GLACIER_IR": 0.005},
}


def test_pricing_absent_returns_none(tmp_path):
    assert load_pricing(None) is None
    assert load_pricing("") is None
    assert load_pricing(str(tmp_path / "missing.json")) is None


def test_pricing_valid_file_loads(tmp_path):
    f = tmp_path / "pricing.json"
    f.write_text(json.dumps(VALID_PRICING))
    assert load_pricing(str(f)) == VALID_PRICING


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({k: v for k, v in VALID_PRICING.items() if k != "source_url"}),
        json.dumps({**VALID_PRICING, "storage_gb_month": {"STANDARD": 0.025}}),
        json.dumps({**VALID_PRICING, "storage_gb_month": {"STANDARD": "x", "STANDARD_IA": 1, "GLACIER_IR": 1}}),
        json.dumps({**VALID_PRICING, "storage_gb_month": {"STANDARD": -1, "STANDARD_IA": 1, "GLACIER_IR": 1}}),
    ],
)
def test_pricing_invalid_file_raises(tmp_path, content):
    f = tmp_path / "pricing.json"
    f.write_text(content)
    with pytest.raises(PricingFileError):
        load_pricing(str(f))
