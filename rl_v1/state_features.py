# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, List, Tuple


def _unit_type(name: str):
    try:
        from sc2.ids.unit_typeid import UnitTypeId
        return UnitTypeId.__members__.get(name)
    except Exception:
        return None


def _upgrade(name: str):
    try:
        from sc2.ids.upgrade_id import UpgradeId
        return UpgradeId.__members__.get(name)
    except Exception:
        return None


def _count_structures(bot, *names: str) -> int:
    total = 0
    for name in names:
        t = _unit_type(name)
        if t is not None:
            try:
                total += bot.structures(t).amount
            except Exception:
                pass
    return int(total)


def _pending_structures(bot, *names: str) -> int:
    total = 0
    for name in names:
        t = _unit_type(name)
        if t is not None:
            try:
                total += int(bot.already_pending(t))
            except Exception:
                pass
    return int(total)


def _count_units(bot, *names: str) -> int:
    total = 0
    for name in names:
        t = _unit_type(name)
        if t is not None:
            try:
                total += bot.units(t).amount
            except Exception:
                pass
    return int(total)


def _has_upgrade(bot, *names: str) -> float:
    upgrades = getattr(bot, "upgrades", set()) or set()
    for name in names:
        u = _upgrade(name)
        if u is not None and u in upgrades:
            return 1.0
    return 0.0


def _level(bot, prefix: str, max_level: int = 3) -> float:
    for level in range(max_level, 0, -1):
        if _has_upgrade(bot, f"{prefix}LEVEL{level}") > 0.5:
            return float(level)
    return 0.0


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _army_supply(bot) -> float:
    try:
        return float(bot.supply_army)
    except Exception:
        return 0.0


def _worker_count(bot) -> float:
    try:
        return float(bot.workers.amount)
    except Exception:
        return 0.0


def _ready_gas_count(bot) -> int:
    return _count_structures(bot, "EXTRACTOR")


def _total_gas_count(bot) -> int:
    return _count_structures(bot, "EXTRACTOR") + _pending_structures(bot, "EXTRACTOR")


def _gas_worker_count(bot) -> int:
    total = 0
    try:
        for gas in bot.gas_buildings.ready:
            total += max(0, int(getattr(gas, "assigned_harvesters", 0) or 0))
    except Exception:
        total = 0
    return int(total)


def _idle_worker_count(bot) -> int:
    try:
        return int(bot.workers.idle.amount)
    except Exception:
        return 0


def _larva_count(bot) -> int:
    return _count_units(bot, "LARVA")


def _queen_count(bot) -> int:
    return _count_units(bot, "QUEEN")


def _mineral_saturation(bot) -> Dict[str, float]:
    """
    经济结构特征。

    重点：16 农左右是满采，超出越多、持续越久，reward 会持续扣分。
    这里使用 townhall.assigned_harvesters / ideal_harvesters 作为近似。
    ideal_harvesters 在矿快干时会下降；这样比固定 16 更稳。
    """
    oversaturated_bases = 0
    undersaturated_bases = 0
    ideal_total = 0
    assigned_total = 0
    overflow_total = 0
    underflow_total = 0
    max_overflow = 0
    max_underflow = 0
    abs_error_total = 0.0
    active_bases = 0

    try:
        for th in bot.townhalls.ready:
            assigned_api = int(getattr(th, "assigned_harvesters", 0) or 0)
            # 有些版本 assigned_harvesters 对真实矿线拥挤不够敏感；用附近工人数兜底。
            try:
                physical_near = int(bot.workers.closer_than(11.5, th).amount)
            except Exception:
                physical_near = assigned_api
            assigned = max(assigned_api, physical_near)
            raw_ideal = int(getattr(th, "ideal_harvesters", 0) or 0)
            # 正常矿区约 16；矿少了以后 ideal 可能低于 16。
            ideal = max(0, min(16, raw_ideal if raw_ideal > 0 else 16))
            if ideal <= 0:
                continue
            active_bases += 1
            ideal_total += ideal
            assigned_total += max(0, assigned)
            overflow = max(0, assigned - ideal)
            underflow = max(0, ideal - assigned)
            overflow_total += overflow
            underflow_total += underflow
            max_overflow = max(max_overflow, overflow)
            max_underflow = max(max_underflow, underflow)
            abs_error_total += abs(assigned - ideal) / max(1.0, float(ideal))
            if overflow >= 2:
                oversaturated_bases += 1
            if underflow >= 4:
                undersaturated_bases += 1
    except Exception:
        pass

    avg_error = abs_error_total / max(1, active_bases)
    return {
        "oversaturated_base_count": float(oversaturated_bases),
        "undersaturated_base_count": float(undersaturated_bases),
        "ideal_worker_total": float(ideal_total),
        "assigned_mineral_workers_total": float(assigned_total),
        "worker_overflow_total": float(overflow_total),
        "worker_underflow_total": float(underflow_total),
        "max_base_overflow": float(max_overflow),
        "max_base_underflow": float(max_underflow),
        "avg_saturation_error": float(avg_error),
    }


def _enemy_intel(bot) -> Dict[str, float]:
    scout = getattr(bot, "scout", None)
    intel = getattr(scout, "intel", None)
    now = _safe_float(getattr(bot, "time", 0.0))
    if intel is None:
        return {
            "enemy_nat_seen": 0.0,
            "enemy_third_seen": 0.0,
            "enemy_army_seen_recent": 0.0,
            "enemy_army_seen_count": 0.0,
            "enemy_tech_seen_count": 0.0,
            "enemy_air_seen": 0.0,
            "enemy_cloak_seen": 0.0,
            "scout_info_age": 999.0,
        }

    tech_seen = set(getattr(intel, "enemy_tech_seen", set()) or set())
    tech_names = " ".join(sorted(str(x).upper() for x in tech_seen))
    army_last_seen = _safe_float(getattr(intel, "enemy_army_last_seen_time", -999.0), -999.0)
    nat_last = _safe_float(getattr(intel, "enemy_natural_last_checked", -999.0), -999.0)
    third_last = _safe_float(getattr(intel, "enemy_third_last_checked", -999.0), -999.0)
    last_info = max(army_last_seen, nat_last, third_last)

    return {
        "enemy_nat_seen": 1.0 if getattr(intel, "enemy_natural_seen", None) is True else 0.0,
        "enemy_third_seen": 1.0 if getattr(intel, "enemy_third_seen", None) is True else 0.0,
        "enemy_army_seen_recent": 1.0 if army_last_seen >= 0 and now - army_last_seen <= 45 else 0.0,
        "enemy_army_seen_count": float(getattr(intel, "enemy_army_last_seen_count", 0) or 0),
        "enemy_tech_seen_count": float(len(tech_seen)),
        "enemy_air_seen": 1.0 if any(k in tech_names for k in ["SPIRE", "STARGATE", "STARPORT", "FLEETBEACON", "PHOENIX", "MUTALISK", "VOIDRAY"]) else 0.0,
        "enemy_cloak_seen": 1.0 if any(k in tech_names for k in ["DARKSHRINE", "BANSHEE", "LURKER", "GHOST"]) else 0.0,
        "scout_info_age": 999.0 if last_info < 0 else max(0.0, now - last_info),
    }


def _visible_threats_near_home(bot) -> Tuple[float, float]:
    try:
        threats = bot.enemy_units.filter(lambda u: not u.is_structure)
        if not threats.exists:
            return 0.0, 0.0
        near_count = 0
        worker_line_count = 0
        for th in bot.townhalls.ready:
            near_count += threats.closer_than(18, th).amount
            worker_line_count += threats.closer_than(10, th).amount
        return float(near_count), float(worker_line_count)
    except Exception:
        return 0.0, 0.0


def _worker_floor(bot, bases: int) -> float:
    t = _safe_float(getattr(bot, "time", 0.0))
    # v2.3: opening model hands off at 2:30.  Do not demand 44 workers on two bases
    # before the third is started, otherwise the bot naturally delays the third.
    if bases <= 1:
        return 20.0
    if bases == 2:
        if t < 150:
            return 24.0
        if t < 240:
            return 32.0
        return 40.0
    if bases == 3:
        return 58.0
    if bases == 4:
        return 66.0
    return 70.0


def _target_bases_by_time(t: float) -> int:
    # v2.3: third hatchery is part of the post-opening skeleton, not a 4:15 event.
    if t < 165:
        return 2
    if t < 405:
        return 3
    if t < 540:
        return 4
    if t < 690:
        return 5
    return 6


PLAN_FEATURE_NAMES = [
    "plan_early_basic_roach_ling_bane",
    "plan_roach_ravager",
    "plan_ling_bane_muta",
    "plan_hydra_lurker",
    "plan_anti_air_hydra_corruptor",
    "plan_ultra_ling_bane",
    "plan_brood_corruptor_viper",
]

STAGE_FEATURE_NAMES = [
    "stage_defense",
    "stage_map_hunt",
    "stage_worker_recovery",
    "stage_economy_buildout",
    "stage_scout",
    "stage_plan_setup",
    "stage_plan_production",
    "stage_timing_attack",
    "stage_late_transition",
]

ALL_PLAN_NAMES = [
    "early_basic_roach_ling_bane",
    "roach_ravager",
    "ling_bane_muta",
    "hydra_lurker",
    "anti_air_hydra_corruptor",
    "ultra_ling_bane",
    "brood_corruptor_viper",
]

TECH_ACTION_TO_OBS_FLAG = {
    "BUILD_ROACH_WARREN": "has_roach_warren",
    "BUILD_BANELING_NEST": "has_baneling_nest",
    "MORPH_LAIR": "has_lair",
    "BUILD_HYDRA_DEN": "has_hydra_den",
    "BUILD_LURKER_DEN": "has_lurker_den",
    "BUILD_SPIRE": "has_spire",
    "BUILD_INFESTATION_PIT": "has_infestation_pit",
    "MORPH_HIVE": "has_hive",
    "BUILD_ULTRALISK_CAVERN": "has_ultra_cavern",
    "BUILD_GREATER_SPIRE": "has_greater_spire",
}

UPGRADE_ACTION_TO_OBS_FLAG = {
    "RESEARCH_ZERGLING_SPEED": "has_ling_speed",
    "RESEARCH_BANELING_SPEED": "has_bane_speed",
    "RESEARCH_ROACH_SPEED": "has_roach_speed",
    "RESEARCH_HYDRA_RANGE": "has_hydra_range",
    "RESEARCH_HYDRA_SPEED": "has_hydra_speed",
    "RESEARCH_NEURAL_PARASITE": "has_neural",
    "RESEARCH_MICROBIAL_SHROUD": "has_microbial_shroud",
}

COMBAT_UNIT_COUNT_KEYS = {
    "ZERGLING": "zergling_count",
    "BANELING": "baneling_count",
    "ROACH": "roach_count",
    "RAVAGER": "ravager_count",
    "HYDRALISK": "hydra_count",
    "LURKER": "lurker_count",
    "INFESTOR": "infestor_count",
    "VIPER": "viper_count",
    "MUTALISK": "mutalisk_count",
    "CORRUPTOR": "corruptor_count",
    "BROODLORD": "broodlord_count",
    "ULTRALISK": "ultralisk_count",
    "OVERSEER": "overseer_count",
}


def _current_plan_name(bot) -> str:
    name = str(getattr(bot, "rl_army_plan", "") or "early_basic_roach_ling_bane")
    if name not in ALL_PLAN_NAMES:
        name = "early_basic_roach_ling_bane"
    return name


def _upgrade_missing_count(obs: Dict[str, float], upgrade_actions) -> float:
    missing = 0.0
    for action in upgrade_actions or []:
        a = str(action).upper()
        flag = UPGRADE_ACTION_TO_OBS_FLAG.get(a)
        if flag is not None:
            missing += 1.0 if obs.get(flag, 0.0) < 0.5 else 0.0
            continue
        # Numeric upgrade levels: count the next relevant level as missing.
        if "MELEE_" in a:
            try:
                need = float(a.rsplit("_", 1)[-1])
                missing += 1.0 if obs.get("melee_level", 0.0) < need else 0.0
            except Exception:
                pass
        elif "MISSILE_ATTACK_" in a:
            try:
                need = float(a.rsplit("_", 1)[-1])
                missing += 1.0 if obs.get("missile_level", 0.0) < need else 0.0
            except Exception:
                pass
        elif "GROUND_ARMOR_" in a:
            try:
                need = float(a.rsplit("_", 1)[-1])
                missing += 1.0 if obs.get("ground_armor_level", 0.0) < need else 0.0
            except Exception:
                pass
        elif "FLYER_ATTACK_" in a:
            try:
                need = float(a.rsplit("_", 1)[-1])
                missing += 1.0 if obs.get("flyer_attack_level", 0.0) < need else 0.0
            except Exception:
                pass
        elif "FLYER_ARMOR_" in a:
            try:
                need = float(a.rsplit("_", 1)[-1])
                missing += 1.0 if obs.get("flyer_armor_level", 0.0) < need else 0.0
            except Exception:
                pass
    return missing


def _desired_gas_for_plan(t: float, base_target: int, requires_hive: bool) -> int:
    if t < 210:
        return min(base_target, 2)
    if t < 330:
        return min(base_target, 4)
    if t < 500 and not requires_hive:
        return min(base_target, 6)
    return max(2, min(base_target, 8))


def _worker_target_cap_for_plan(plan_name: str, t: float, bases: float, plan_requires_hive: bool) -> float:
    # This is a cap, not a floor.  It teaches "stop droning and use the economy".
    if t < 240:
        cap = 44.0
    elif t < 390:
        cap = 62.0
    elif plan_name == "roach_ravager" and t < 660:
        cap = 76.0
    elif plan_name == "early_basic_roach_ling_bane" and t < 540:
        cap = 70.0
    elif plan_requires_hive:
        cap = 84.0
    else:
        cap = 82.0
    if bases <= 2:
        cap = min(cap, 46.0)
    elif bases <= 3:
        cap = min(cap, 68.0)
    elif bases <= 4:
        cap = min(cap, 80.0)
    return cap


def _enemy_structure_visible(bot) -> float:
    try:
        return 1.0 if getattr(bot, "enemy_structures", None) is not None and bot.enemy_structures.exists else 0.0
    except Exception:
        return 0.0


def _plan_and_stage_features(bot, obs: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    plan_name = _current_plan_name(bot)
    for n in ALL_PLAN_NAMES:
        out[f"plan_{n}"] = 1.0 if plan_name == n else 0.0

    try:
        from rl_v1.tech_intent import PLANS
        plan = PLANS.get(plan_name) or PLANS["early_basic_roach_ling_bane"]
    except Exception:
        plan = None

    t = float(obs.get("game_time", 0.0) or 0.0)
    bases = float(obs.get("base_count", 0.0) or 0.0)
    workers = float(obs.get("worker_count", 0.0) or 0.0)
    total_gas = float(obs.get("total_gas_count", 0.0) or 0.0)
    minerals = float(obs.get("minerals", 0.0) or 0.0)
    vespene = float(obs.get("vespene", 0.0) or 0.0)
    supply = float(obs.get("supply_used", 0.0) or 0.0)
    army = float(obs.get("army_supply", 0.0) or 0.0)

    counts = {u: float(obs.get(key, 0.0) or 0.0) for u, key in COMBAT_UNIT_COUNT_KEYS.items()}
    total_units = max(1.0, sum(counts.values()))

    main_units = set(getattr(plan, "main_units", ()) or ()) if plan is not None else set()
    support_units = set(getattr(plan, "support_units", ()) or ()) if plan is not None else set()
    allowed_units = main_units | support_units
    main_count = sum(counts.get(u, 0.0) for u in main_units)
    support_count = sum(counts.get(u, 0.0) for u in support_units)
    offplan_count = sum(v for u, v in counts.items() if u not in allowed_units and v > 0)

    support_overcap = 0.0
    support_caps = getattr(plan, "support_caps", {}) if plan is not None else {}
    for unit_name, cap in (support_caps or {}).items():
        support_overcap += max(0.0, counts.get(unit_name, 0.0) - float(cap))

    tech_missing = 0.0
    for tech_action in getattr(plan, "tech", ()) if plan is not None else ():
        flag = TECH_ACTION_TO_OBS_FLAG.get(str(tech_action).upper())
        if flag is not None and obs.get(flag, 0.0) < 0.5:
            tech_missing += 1.0

    upgrade_missing = _upgrade_missing_count(obs, getattr(plan, "upgrades", ()) if plan is not None else ())
    requires_lair = 1.0 if bool(getattr(plan, "requires_lair", False)) else 0.0
    requires_hive = 1.0 if bool(getattr(plan, "requires_hive", False)) else 0.0
    gas_target = float(getattr(plan, "gas_target", 2) if plan is not None else 2)
    desired_gas = float(_desired_gas_for_plan(t, int(gas_target), bool(requires_hive)))
    gas_debt = max(0.0, desired_gas - total_gas)
    worker_cap = _worker_target_cap_for_plan(plan_name, t, bases, bool(requires_hive))

    # v2.7: plan consistency curriculum.  The selector may choose a high-level
    # composition, but RL must learn to actually realize it.  These features expose
    # whether the selected plan is still only words: no required tech, no main units,
    # and a mostly off-plan army.
    try:
        plan_since = float(getattr(bot, "rl_army_plan_since", t) or t)
    except Exception:
        plan_since = t
    plan_age = max(0.0, t - plan_since)
    plan_is_late = 1.0 if (bool(requires_hive) or plan_name in {"ultra_ling_bane", "brood_corruptor_viper"}) else 0.0

    enemy_visible_struct = _enemy_structure_visible(bot)
    scout_age = float(obs.get("scout_info_age", 999.0) or 999.0)
    enemy_tech_count = float(obs.get("enemy_tech_seen_count", 0.0) or 0.0)
    threats = float(obs.get("visible_threats_near_home", 0.0) or 0.0)
    worker_line = float(obs.get("visible_threats_worker_line", 0.0) or 0.0)

    spend_bank = max(0.0, (minerals - 1200.0) / 1200.0) + max(0.0, (vespene - 600.0) / 800.0)
    spend_bank = max(0.0, min(3.0, spend_bank))

    late_transition_due = 1.0 if (
        threats < 8
        and worker_line < 2
        and obs.get("has_hive", 0.0) < 0.5
        and bases >= 4
        and workers >= 70
        and (t >= 620 or supply >= 185 or army >= 105)
    ) else 0.0

    timing_attack_due = 1.0 if (
        threats < 8
        and worker_line < 2
        and obs.get("worker_recovery", 0.0) < 0.5
        and obs.get("expand_debt", 0.0) < 0.5
        and ((supply >= 165 and army >= 82) or (supply >= 190 and army >= 95) or spend_bank >= 1.0)
    ) else 0.0

    scout_due = 1.0 if (
        threats < 8
        and ((t >= 300 and scout_age >= 85) or (t >= 390 and enemy_tech_count < 1) or (t >= 520 and enemy_tech_count < 2))
    ) else 0.0

    plan_setup_due = 1.0 if (
        threats < 8
        and obs.get("expand_debt", 0.0) < 0.5
        and obs.get("worker_recovery", 0.0) < 0.5
        and t >= 240
        and (tech_missing > 0 or gas_debt > 0 or (upgrade_missing >= 2 and army >= 35))
    ) else 0.0

    map_hunt_due = 1.0 if (
        t >= 500
        and supply >= 170
        and army >= 70
        and enemy_visible_struct < 0.5
        and threats < 8
    ) else 0.0

    main_ratio = float(main_count / total_units)
    offplan_ratio = float(offplan_count / total_units)
    plan_unrealized = 1.0 if (
        t >= 360
        and plan_age >= 90
        and army >= 45
        and main_ratio < 0.22
        and (tech_missing > 0 or offplan_ratio > 0.50)
    ) else 0.0
    plan_stuck = 1.0 if (
        (plan_unrealized > 0.5 and plan_age >= 150 and (tech_missing >= 2 or offplan_ratio >= 0.65))
        or (plan_is_late > 0.5 and t >= 540 and obs.get("has_hive", 0.0) < 0.5 and army >= 80 and offplan_ratio >= 0.55)
    ) else 0.0
    plan_should_tech = 1.0 if (plan_setup_due > 0.5 or late_transition_due > 0.5 or plan_stuck > 0.5) else 0.0
    plan_should_attack = 1.0 if (timing_attack_due > 0.5 or map_hunt_due > 0.5) else 0.0

    out.update({
        "enemy_structure_visible": enemy_visible_struct,
        "plan_main_unit_count": float(main_count),
        "plan_support_unit_count": float(support_count),
        "plan_offplan_unit_count": float(offplan_count),
        "plan_main_ratio": main_ratio,
        "plan_support_ratio": float(support_count / total_units),
        "plan_offplan_ratio": offplan_ratio,
        "plan_support_overcap": float(support_overcap),
        "plan_tech_missing_count": float(tech_missing),
        "plan_upgrade_missing_count": float(upgrade_missing),
        "plan_gas_target": float(desired_gas),
        "plan_gas_debt": float(gas_debt),
        "plan_needs_lair": requires_lair,
        "plan_needs_hive": requires_hive,
        "plan_age": float(plan_age),
        "plan_is_late": float(plan_is_late),
        "plan_unrealized": float(plan_unrealized),
        "plan_stuck": float(plan_stuck),
        "plan_should_tech": float(plan_should_tech),
        "plan_should_attack": float(plan_should_attack),
        "worker_target_cap": float(worker_cap),
        "worker_excess": max(0.0, workers - worker_cap),
        "scout_due": scout_due,
        "timing_attack_due": timing_attack_due,
        "late_transition_due": late_transition_due,
        "plan_setup_due": plan_setup_due,
        "map_hunt_due": map_hunt_due,
        "spend_bank_urgency": spend_bank,
    })

    try:
        from rl_v1.strategic_stage import stage_features
        out.update(stage_features({**obs, **out}))
    except Exception:
        for k in STAGE_FEATURE_NAMES:
            out[k] = 0.0
        out["stage_plan_production"] = 1.0
        out["strategic_stage_id"] = 6.0
    return out


FEATURE_NAMES: List[str] = [
    # economy
    "game_time", "minerals", "vespene", "supply_used", "supply_cap", "supply_left",
    "worker_count", "army_supply", "base_count", "pending_base_count", "larva_count", "queen_count",
    "idle_worker_count", "ready_gas_count", "total_gas_count", "gas_worker_count",
    "gas_worker_target", "gas_worker_debt", "gas_economy_emergency", "mineral_gas_ratio",
    "oversaturated_base_count", "undersaturated_base_count", "ideal_worker_total", "assigned_mineral_workers_total",
    "worker_overflow_total", "worker_underflow_total", "max_base_overflow", "max_base_underflow", "avg_saturation_error",
    "worker_floor", "worker_deficit",
    # tech structures
    "has_pool", "has_lair", "has_hive", "has_roach_warren", "has_baneling_nest",
    "has_hydra_den", "has_lurker_den", "has_infestation_pit", "has_spire", "has_greater_spire", "has_ultra_cavern",
    # upgrades / tech levels
    "melee_level", "missile_level", "ground_armor_level", "flyer_attack_level", "flyer_armor_level",
    "has_ling_speed", "has_bane_speed", "has_roach_speed", "has_hydra_range", "has_hydra_speed",
    "has_neural", "has_microbial_shroud",
    # own army composition
    "zergling_count", "baneling_count", "roach_count", "ravager_count", "hydra_count", "lurker_count",
    "infestor_count", "viper_count", "mutalisk_count", "corruptor_count", "broodlord_count", "ultralisk_count",
    # intel / threats
    "enemy_nat_seen", "enemy_third_seen", "enemy_army_seen_recent", "enemy_army_seen_count",
    "enemy_tech_seen_count", "enemy_air_seen", "enemy_cloak_seen", "scout_info_age",
    "visible_threats_near_home", "visible_threats_worker_line",
    "enemy_natural_missing_signal", "enemy_pressure_score", "early_allin_danger",
    # rule debts / simple flags
    "worker_recovery", "expand_debt", "hive_debt", "gas_starved", "bank_too_high", "near_maxed",
    # v2.4 competition-thinking features: plan identity, composition coherence, stages
    *PLAN_FEATURE_NAMES,
    "enemy_structure_visible",
    "plan_main_unit_count", "plan_support_unit_count", "plan_offplan_unit_count",
    "plan_main_ratio", "plan_support_ratio", "plan_offplan_ratio", "plan_support_overcap",
    "plan_tech_missing_count", "plan_upgrade_missing_count", "plan_gas_target", "plan_gas_debt",
    "plan_needs_lair", "plan_needs_hive",
    "plan_age", "plan_is_late", "plan_unrealized", "plan_stuck", "plan_should_tech", "plan_should_attack",
    "worker_target_cap", "worker_excess",
    "scout_due", "timing_attack_due", "late_transition_due", "plan_setup_due", "map_hunt_due", "spend_bank_urgency",
    *STAGE_FEATURE_NAMES, "strategic_stage_id",
]


def extract_observation(bot) -> Dict[str, float]:
    bases = 0
    pending_bases = 0
    try:
        bases = int(bot.townhalls.ready.amount)
        pending_bases = int(bot.townhalls.amount - bot.townhalls.ready.amount)
    except Exception:
        pass

    sat = _mineral_saturation(bot)
    worker_count = _worker_count(bot)
    floor = _worker_floor(bot, bases)
    scout = _enemy_intel(bot)
    near_threats, worker_line_threats = _visible_threats_near_home(bot)

    minerals = _safe_float(getattr(bot, "minerals", 0))
    vespene = _safe_float(getattr(bot, "vespene", 0))
    supply_used = _safe_float(getattr(bot, "supply_used", 0))
    supply_cap = _safe_float(getattr(bot, "supply_cap", 0))
    army_supply = _army_supply(bot)
    t = _safe_float(getattr(bot, "time", 0.0))

    obs: Dict[str, float] = {
        "game_time": t,
        "minerals": minerals,
        "vespene": vespene,
        "supply_used": supply_used,
        "supply_cap": supply_cap,
        "supply_left": max(0.0, supply_cap - supply_used),
        "worker_count": worker_count,
        "army_supply": army_supply,
        "base_count": float(bases),
        "pending_base_count": float(pending_bases),
        "larva_count": float(_larva_count(bot)),
        "queen_count": float(_queen_count(bot)),
        "idle_worker_count": float(_idle_worker_count(bot)),
        "ready_gas_count": float(_ready_gas_count(bot)),
        "total_gas_count": float(_total_gas_count(bot)),
        "gas_worker_count": float(_gas_worker_count(bot)),
        **sat,
        "worker_floor": floor,
        "worker_deficit": max(0.0, floor - worker_count),
        "has_pool": 1.0 if _count_structures(bot, "SPAWNINGPOOL") > 0 else 0.0,
        "has_lair": 1.0 if _count_structures(bot, "LAIR", "HIVE") > 0 else 0.0,
        "has_hive": 1.0 if _count_structures(bot, "HIVE") > 0 else 0.0,
        "has_roach_warren": 1.0 if _count_structures(bot, "ROACHWARREN") > 0 else 0.0,
        "has_baneling_nest": 1.0 if _count_structures(bot, "BANELINGNEST") > 0 else 0.0,
        "has_hydra_den": 1.0 if _count_structures(bot, "HYDRALISKDEN") > 0 else 0.0,
        "has_lurker_den": 1.0 if _count_structures(bot, "LURKERDENMP", "LURKERDEN") > 0 else 0.0,
        "has_infestation_pit": 1.0 if _count_structures(bot, "INFESTATIONPIT") > 0 else 0.0,
        "has_spire": 1.0 if _count_structures(bot, "SPIRE", "GREATERSPIRE") > 0 else 0.0,
        "has_greater_spire": 1.0 if _count_structures(bot, "GREATERSPIRE") > 0 else 0.0,
        "has_ultra_cavern": 1.0 if _count_structures(bot, "ULTRALISKCAVERN") > 0 else 0.0,
        "melee_level": _level(bot, "ZERGMELEEWEAPONS"),
        "missile_level": _level(bot, "ZERGMISSILEWEAPONS"),
        "ground_armor_level": _level(bot, "ZERGGROUNDARMORS"),
        "flyer_attack_level": _level(bot, "ZERGFLYERWEAPONS"),
        "flyer_armor_level": _level(bot, "ZERGFLYERARMORS"),
        "has_ling_speed": _has_upgrade(bot, "ZERGLINGMOVEMENTSPEED"),
        "has_bane_speed": _has_upgrade(bot, "CENTRIFICALHOOKS"),
        "has_roach_speed": _has_upgrade(bot, "GLIALRECONSTITUTION"),
        "has_hydra_range": _has_upgrade(bot, "EVOLVEGROOVEDSPINES"),
        "has_hydra_speed": _has_upgrade(bot, "EVOLVEMUSCULARAUGMENTS"),
        "has_neural": _has_upgrade(bot, "NEURALPARASITE"),
        "has_microbial_shroud": _has_upgrade(bot, "MICROBIALSHROUD"),
        "zergling_count": float(_count_units(bot, "ZERGLING")),
        "baneling_count": float(_count_units(bot, "BANELING")),
        "roach_count": float(_count_units(bot, "ROACH")),
        "ravager_count": float(_count_units(bot, "RAVAGER")),
        "hydra_count": float(_count_units(bot, "HYDRALISK")),
        "lurker_count": float(_count_units(bot, "LURKERMP", "LURKER")),
        "infestor_count": float(_count_units(bot, "INFESTOR")),
        "viper_count": float(_count_units(bot, "VIPER")),
        "mutalisk_count": float(_count_units(bot, "MUTALISK")),
        "corruptor_count": float(_count_units(bot, "CORRUPTOR")),
        "broodlord_count": float(_count_units(bot, "BROODLORD")),
        "ultralisk_count": float(_count_units(bot, "ULTRALISK")),
        **scout,
        "visible_threats_near_home": near_threats,
        "visible_threats_worker_line": worker_line_threats,
        # v2.5 anti-all-in features.  These are intentionally coarse: the policy
        # should learn from them, while the combat/rule layer still executes concrete defense.
        "enemy_natural_missing_signal": 1.0 if (t >= 210 and scout.get("enemy_nat_seen", 0.0) < 0.5 and scout.get("scout_info_age", 999.0) < 180) else 0.0,
        "enemy_pressure_score": float(near_threats + 2.0 * worker_line_threats + max(0.0, scout.get("enemy_army_seen_count", 0.0) - 6.0) * 0.25),
        "early_allin_danger": 1.0 if (
            t < 520 and (
                near_threats >= 5
                or worker_line_threats >= 1
                or (t >= 230 and scout.get("enemy_nat_seen", 0.0) < 0.5 and scout.get("enemy_army_seen_count", 0.0) >= 8)
            )
        ) else 0.0,
        "worker_recovery": 1.0 if worker_count < floor else 0.0,
        "expand_debt": 1.0 if bases + pending_bases < _target_bases_by_time(t) else 0.0,
        "hive_debt": 1.0 if t >= 480 and _count_structures(bot, "HIVE") == 0 else 0.0,
        "gas_starved": 1.0 if minerals >= 700 and vespene <= 150 else 0.0,
        "bank_too_high": 1.0 if minerals >= 1200 or vespene >= 800 else 0.0,
        "near_maxed": 1.0 if supply_used >= 185 else 0.0,
    }

    # v2.8 gas-economy features.  These make the 9000 mineral / 34 gas failure visible
    # to the policy and reward, while the baseline manager handles the concrete workerflow.
    gas_worker_target = min(obs.get("ready_gas_count", 0.0), max(0.0, obs.get("total_gas_count", 0.0))) * 3.0
    if t >= 330 and minerals >= 1000 and vespene < 350:
        gas_worker_target = obs.get("ready_gas_count", 0.0) * 3.0
    obs["gas_worker_target"] = float(gas_worker_target)
    obs["gas_worker_debt"] = max(0.0, gas_worker_target - obs.get("gas_worker_count", 0.0))
    obs["gas_economy_emergency"] = 1.0 if (
        (t >= 300 and minerals >= 1200 and vespene <= 250)
        or (t >= 420 and minerals >= 1800 and vespene <= 420)
        or (t >= 540 and minerals >= 2500 and vespene <= 700)
    ) else 0.0
    obs["mineral_gas_ratio"] = float(min(60.0, minerals / max(1.0, vespene)))

    obs.update(_plan_and_stage_features(bot, obs))

    for name in FEATURE_NAMES:
        obs.setdefault(name, 0.0)
    return obs


def vectorize_observation(obs: Dict[str, float]) -> List[float]:
    scales = {
        "game_time": 900.0,
        "minerals": 2000.0,
        "vespene": 1000.0,
        "supply_used": 200.0,
        "supply_cap": 200.0,
        "supply_left": 50.0,
        "worker_count": 90.0,
        "army_supply": 160.0,
        "base_count": 8.0,
        "pending_base_count": 3.0,
        "larva_count": 30.0,
        "queen_count": 10.0,
        "idle_worker_count": 20.0,
        "ready_gas_count": 10.0,
        "total_gas_count": 12.0,
        "gas_worker_count": 30.0,
        "gas_worker_target": 30.0,
        "gas_worker_debt": 18.0,
        "mineral_gas_ratio": 30.0,
        "oversaturated_base_count": 5.0,
        "undersaturated_base_count": 5.0,
        "ideal_worker_total": 90.0,
        "assigned_mineral_workers_total": 90.0,
        "worker_overflow_total": 30.0,
        "worker_underflow_total": 50.0,
        "max_base_overflow": 16.0,
        "max_base_underflow": 16.0,
        "avg_saturation_error": 2.0,
        "worker_floor": 90.0,
        "worker_deficit": 40.0,
        "enemy_army_seen_count": 80.0,
        "enemy_tech_seen_count": 20.0,
        "scout_info_age": 180.0,
        "visible_threats_near_home": 80.0,
        "visible_threats_worker_line": 40.0,
        "enemy_pressure_score": 80.0,
        "plan_main_unit_count": 120.0,
        "plan_support_unit_count": 60.0,
        "plan_offplan_unit_count": 120.0,
        "plan_support_overcap": 30.0,
        "plan_tech_missing_count": 8.0,
        "plan_upgrade_missing_count": 10.0,
        "plan_gas_target": 8.0,
        "plan_gas_debt": 8.0,
        "plan_age": 300.0,
        "worker_target_cap": 90.0,
        "worker_excess": 25.0,
        "spend_bank_urgency": 3.0,
        "strategic_stage_id": 8.0,
    }
    vec = []
    for name in FEATURE_NAMES:
        value = float(obs.get(name, 0.0))
        scale = scales.get(name, 1.0)
        if scale <= 1.0:
            vec.append(max(0.0, min(1.0, value)))
        else:
            vec.append(max(-5.0, min(5.0, value / scale)))
    return vec


FEATURE_DIM = len(FEATURE_NAMES)
