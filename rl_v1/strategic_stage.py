# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, List, Set


STAGE_NAMES: List[str] = [
    "defense",
    "map_hunt",
    "worker_recovery",
    "economy_buildout",
    "scout",
    "plan_setup",
    "plan_production",
    "timing_attack",
    "late_transition",
]

ATTACK_ACTIONS: Set[str] = {"ROACH_HYDRA_TIMING", "MAXED_ATTACK"}
TECH_ACTIONS: Set[str] = {"FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS"}
ECON_ACTIONS: Set[str] = {"ECON_MACRO"}
SCOUT_ACTIONS: Set[str] = {"SCOUT_FOCUS"}
DEFENSE_ACTIONS: Set[str] = {"DEFENSIVE_HOLD"}


def _f(obs: Dict[str, float], key: str, default: float = 0.0) -> float:
    try:
        return float(obs.get(key, default) or default)
    except Exception:
        return default


def _real_defense_pressure(obs: Dict[str, float]) -> bool:
    """Return True only for pressure that actually deserves defense.

    v2.6 sometimes ended games with stage=defense even after a victory because a few
    visible enemy units near the edge of our territory kept the stage pinned to defense.
    In v2.7, defense is reserved for worker-line pressure, strong early all-in signals,
    or a materially dangerous number of threats near bases.  A maxed army with two stray
    units nearby should attack/transition, not stare at home.
    """
    t = _f(obs, "game_time")
    threats = _f(obs, "visible_threats_near_home")
    worker_line = _f(obs, "visible_threats_worker_line")
    early_allin = _f(obs, "early_allin_danger") > 0.5
    army = _f(obs, "army_supply")
    supply = _f(obs, "supply_used")

    if worker_line >= 1:
        return True
    if early_allin:
        return True
    if threats >= 10:
        return True
    # Midgame with low army: even 6-9 enemy units near home can be fatal.
    if t < 520 and threats >= 6 and army < 80:
        return True
    # Late-game defense only if it is not just a couple of scouts/stragglers.
    if supply < 170 and threats >= 8:
        return True
    return False


def infer_stage(obs: Dict[str, float]) -> str:
    """Infer the current high-level strategic training stage from observation features.

    This is a teacher signal for RL, not a hand-written bot script.  The stage only
    shapes reward and masks absurd actions; the policy still learns which strategic
    intent to choose.
    """
    if _real_defense_pressure(obs):
        return "defense"

    if _f(obs, "map_hunt_due") > 0.5:
        return "map_hunt"

    supply = _f(obs, "supply_used")
    if _f(obs, "worker_recovery") > 0.5 and supply < 180:
        return "worker_recovery"

    if _f(obs, "expand_debt") > 0.5 and _f(obs, "game_time") < 560:
        return "economy_buildout"

    # If a selected composition is not actually being realized, first fix the tech / gas /
    # production chain before attacking with a random off-plan army.
    if _f(obs, "plan_stuck") > 0.5 or _f(obs, "plan_unrealized") > 0.5:
        return "plan_setup"

    if _f(obs, "timing_attack_due") > 0.5:
        return "timing_attack"

    if _f(obs, "late_transition_due") > 0.5:
        return "late_transition"

    if _f(obs, "scout_due") > 0.5:
        return "scout"

    if _f(obs, "plan_setup_due") > 0.5:
        return "plan_setup"

    army = _f(obs, "army_supply")
    if supply >= 185 or army >= 90:
        return "timing_attack"
    return "plan_production"


def stage_features(obs: Dict[str, float]) -> Dict[str, float]:
    stage = infer_stage(obs)
    features = {f"stage_{name}": 1.0 if stage == name else 0.0 for name in STAGE_NAMES}
    features["strategic_stage_id"] = float(STAGE_NAMES.index(stage)) if stage in STAGE_NAMES else 0.0
    return features


def recommended_actions(stage: str, obs: Dict[str, float]) -> Set[str]:
    """Return a soft teacher set of action names for reward shaping."""
    if stage == "defense":
        return {"DEFENSIVE_HOLD", "ROACH_PRESSURE"}
    if stage == "map_hunt":
        return {"MAXED_ATTACK", "SCOUT_FOCUS"}
    if stage == "worker_recovery":
        return {"ECON_MACRO", "DEFENSIVE_HOLD"}
    if stage == "economy_buildout":
        return {"ECON_MACRO", "SCOUT_FOCUS"}
    if stage == "scout":
        return {"SCOUT_FOCUS", "ECON_MACRO"}
    if stage == "plan_setup":
        # Plan setup now includes gas/tech/upgrades, and ECON_MACRO can still build gas.
        return {"FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS", "ECON_MACRO"}
    if stage == "late_transition":
        return {"FAST_HIVE_TECH", "UPGRADE_FOCUS", "SCOUT_FOCUS"}
    if stage == "timing_attack":
        return {"ROACH_HYDRA_TIMING", "MAXED_ATTACK"}
    return {"ROACH_HYDRA_TIMING", "ECON_MACRO", "UPGRADE_FOCUS"}


def is_clearly_bad_action(stage: str, action_name: str, obs: Dict[str, float]) -> bool:
    """Only mark actions that are strategically absurd, not merely suboptimal."""
    a = str(action_name or "").upper()
    supply = _f(obs, "supply_used")
    army = _f(obs, "army_supply")
    expand_debt = _f(obs, "expand_debt") > 0.5
    threats = _f(obs, "visible_threats_near_home")
    worker_line = _f(obs, "visible_threats_worker_line")

    if _real_defense_pressure(obs):
        if a in {"SCOUT_FOCUS", "FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS", "DO_NOTHING", "MAXED_ATTACK", "LING_PRESSURE"}:
            return True
        if a == "ECON_MACRO" and (threats >= 6 or worker_line >= 1):
            return True

    # DO_NOTHING is only acceptable in low-pressure scouting/production gaps.  Near max,
    # while stuck, or during transition, it should be learned as a bad choice.
    if a == "DO_NOTHING":
        if supply >= 170 or _f(obs, "bank_too_high") > 0.5 or _f(obs, "spend_bank_urgency") >= 0.8:
            return True
        if stage in {"defense", "timing_attack", "map_hunt", "late_transition", "plan_setup", "economy_buildout"}:
            return True
        if _f(obs, "plan_stuck") > 0.5 or _f(obs, "plan_unrealized") > 0.5:
            return True

    if supply >= 198 and a == "ECON_MACRO" and not expand_debt:
        return True
    if stage == "late_transition" and a in {"LING_PRESSURE", "ROACH_PRESSURE"} and supply >= 150:
        return True
    if stage == "economy_buildout" and a in {"MAXED_ATTACK", "ROACH_HYDRA_TIMING"} and army < 80 and supply < 150:
        return True
    if stage == "plan_setup" and _f(obs, "plan_tech_missing_count") > 0.5 and a in {"MAXED_ATTACK", "LING_PRESSURE"}:
        return True
    return False
