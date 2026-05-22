# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple


def _u(name: str):
    try:
        from sc2.ids.unit_typeid import UnitTypeId
        return UnitTypeId.__members__.get(str(name).upper())
    except Exception:
        return None


@dataclass(frozen=True)
class ArmyPlan:
    """A sticky, task-driven army composition intent.

    This is deliberately NOT a hard-coded default tech route.  The selector chooses
    exactly one main plan from current scouting evidence, then all tech / upgrades /
    production serve that plan.  The important invariant is: one main army identity
    at a time; support units are capped and never become random scatter.
    """

    name: str
    main_units: Tuple[str, ...]
    support_units: Tuple[str, ...] = ()
    tech: Tuple[str, ...] = ()
    upgrades: Tuple[str, ...] = ()
    gas_target: int = 2
    requires_lair: bool = False
    requires_hive: bool = False
    description: str = ""
    # Desired relative weights among combat units.  Missing units mean "not part of this plan".
    unit_weights: Dict[str, float] = field(default_factory=dict)
    # Hard cap for support units to avoid "one of everything".
    support_caps: Dict[str, int] = field(default_factory=dict)


PLANS: Dict[str, ArmyPlan] = {
    # Early / low-intel bridge.  This is allowed because user explicitly accepts
    # early roach/ling/bane as a basic skeleton.  It should NOT keep teching forever.
    "early_basic_roach_ling_bane": ArmyPlan(
        name="early_basic_roach_ling_bane",
        main_units=("ROACH", "ZERGLING"),
        support_units=("BANELING", "RAVAGER"),
        tech=("BUILD_ROACH_WARREN", "BUILD_BANELING_NEST"),
        upgrades=("RESEARCH_ZERGLING_SPEED", "RESEARCH_ROACH_SPEED", "RESEARCH_BANELING_SPEED"),
        gas_target=2,
        requires_lair=False,
        description="low-intel early bridge: ling/roach/bane only; do not branch into late tech yet",
        unit_weights={"ROACH": 0.48, "ZERGLING": 0.34, "BANELING": 0.10, "RAVAGER": 0.08},
        support_caps={"BANELING": 18, "RAVAGER": 8},
    ),
    "roach_ravager": ArmyPlan(
        name="roach_ravager",
        main_units=("ROACH", "RAVAGER"),
        support_units=("ZERGLING",),
        tech=("BUILD_ROACH_WARREN", "MORPH_LAIR"),
        upgrades=("RESEARCH_ROACH_SPEED", "RESEARCH_MISSILE_ATTACK_1", "RESEARCH_GROUND_ARMOR_1", "RESEARCH_MISSILE_ATTACK_2", "RESEARCH_GROUND_ARMOR_2"),
        gas_target=4,
        requires_lair=True,
        description="armored ground answer: concentrated roach/ravager core",
        unit_weights={"ROACH": 0.68, "RAVAGER": 0.22, "ZERGLING": 0.10},
        support_caps={"ZERGLING": 24},
    ),
    "ling_bane_muta": ArmyPlan(
        name="ling_bane_muta",
        main_units=("MUTALISK", "ZERGLING", "BANELING"),
        support_units=("CORRUPTOR",),
        tech=("MORPH_LAIR", "BUILD_BANELING_NEST", "BUILD_SPIRE"),
        upgrades=("RESEARCH_ZERGLING_SPEED", "RESEARCH_BANELING_SPEED", "RESEARCH_MELEE_1", "RESEARCH_FLYER_ATTACK_1", "RESEARCH_MELEE_2", "RESEARCH_FLYER_ATTACK_2"),
        gas_target=6,
        requires_lair=True,
        description="greedy/low anti-air punish: muta + ling/bane; no hydra/lurker scatter",
        unit_weights={"MUTALISK": 0.42, "ZERGLING": 0.38, "BANELING": 0.16, "CORRUPTOR": 0.04},
        support_caps={"CORRUPTOR": 8},
    ),
    "hydra_lurker": ArmyPlan(
        name="hydra_lurker",
        main_units=("HYDRALISK", "LURKER"),
        support_units=("ROACH", "VIPER", "OVERSEER"),
        tech=("MORPH_LAIR", "BUILD_HYDRA_DEN", "BUILD_LURKER_DEN"),
        upgrades=("RESEARCH_HYDRA_RANGE", "RESEARCH_HYDRA_SPEED", "RESEARCH_LURKER_RANGE", "RESEARCH_MISSILE_ATTACK_1", "RESEARCH_GROUND_ARMOR_1", "RESEARCH_MISSILE_ATTACK_2", "RESEARCH_GROUND_ARMOR_2"),
        gas_target=6,
        requires_lair=True,
        description="ground deathball / splash answer: hydra-lurker main army",
        unit_weights={"HYDRALISK": 0.52, "LURKER": 0.28, "ROACH": 0.12, "VIPER": 0.05, "OVERSEER": 0.03},
        support_caps={"ROACH": 18, "VIPER": 3, "OVERSEER": 2},
    ),
    "anti_air_hydra_corruptor": ArmyPlan(
        name="anti_air_hydra_corruptor",
        main_units=("HYDRALISK", "CORRUPTOR"),
        support_units=("ROACH", "VIPER", "OVERSEER"),
        tech=("MORPH_LAIR", "BUILD_HYDRA_DEN", "BUILD_SPIRE"),
        upgrades=("RESEARCH_HYDRA_RANGE", "RESEARCH_HYDRA_SPEED", "RESEARCH_MISSILE_ATTACK_1", "RESEARCH_FLYER_ATTACK_1", "RESEARCH_GROUND_ARMOR_1", "RESEARCH_FLYER_ARMOR_1"),
        gas_target=6,
        requires_lair=True,
        description="enemy air / air tech answer: hydra-corruptor core",
        unit_weights={"HYDRALISK": 0.56, "CORRUPTOR": 0.24, "ROACH": 0.10, "VIPER": 0.06, "OVERSEER": 0.04},
        support_caps={"ROACH": 16, "VIPER": 3, "OVERSEER": 3},
    ),
    "ultra_ling_bane": ArmyPlan(
        name="ultra_ling_bane",
        main_units=("ULTRALISK", "ZERGLING", "BANELING"),
        support_units=("INFESTOR", "VIPER"),
        tech=("MORPH_LAIR", "BUILD_INFESTATION_PIT", "MORPH_HIVE", "BUILD_ULTRALISK_CAVERN", "BUILD_BANELING_NEST"),
        upgrades=("RESEARCH_ZERGLING_SPEED", "RESEARCH_BANELING_SPEED", "RESEARCH_ADRENAL", "RESEARCH_MELEE_1", "RESEARCH_GROUND_ARMOR_1", "RESEARCH_MELEE_2", "RESEARCH_GROUND_ARMOR_2", "RESEARCH_ULTRA_ARMOR", "RESEARCH_ULTRA_SPEED"),
        gas_target=8,
        requires_lair=True,
        requires_hive=True,
        description="mass light/bio answer: ultra-ling-bane main army",
        unit_weights={"ULTRALISK": 0.34, "ZERGLING": 0.42, "BANELING": 0.16, "INFESTOR": 0.04, "VIPER": 0.04},
        support_caps={"INFESTOR": 3, "VIPER": 3},
    ),
    "brood_corruptor_viper": ArmyPlan(
        name="brood_corruptor_viper",
        main_units=("BROODLORD", "CORRUPTOR", "VIPER"),
        support_units=("HYDRALISK", "OVERSEER"),
        tech=("MORPH_LAIR", "BUILD_SPIRE", "BUILD_INFESTATION_PIT", "MORPH_HIVE", "BUILD_GREATER_SPIRE"),
        upgrades=("RESEARCH_FLYER_ATTACK_1", "RESEARCH_FLYER_ARMOR_1", "RESEARCH_FLYER_ATTACK_2", "RESEARCH_FLYER_ARMOR_2"),
        gas_target=8,
        requires_lair=True,
        requires_hive=True,
        description="turtle/static/slow ground army answer: brood-corruptor-viper",
        unit_weights={"BROODLORD": 0.34, "CORRUPTOR": 0.38, "VIPER": 0.10, "HYDRALISK": 0.14, "OVERSEER": 0.04},
        support_caps={"VIPER": 4, "HYDRALISK": 18, "OVERSEER": 3},
    ),
}


class TechIntentSelector:
    """Selects a sticky main army plan from scouting evidence.

    The selector is intentionally simple and inspectable.  It gives the RL model a
    direction to learn toward, without pretending the neural policy already knows SC2
    composition theory.  It does not force a default late-game tech route; unknown
    information keeps the bot on cheap early units and increases scout intent.
    """

    def __init__(self, bot, min_plan_duration: float = 75.0):
        self.bot = bot
        self.min_plan_duration = float(min_plan_duration)
        self.current_plan_name = "early_basic_roach_ling_bane"
        self.current_reason = "initial early bridge"
        self.last_switch_time = -999.0
        self.last_scores: Dict[str, float] = {}

    def current_plan(self) -> ArmyPlan:
        self.update()
        return PLANS[self.current_plan_name]

    def describe(self) -> str:
        p = self.current_plan()
        return f"{p.name}: main={list(p.main_units)} support={list(p.support_units)} reason={self.current_reason}"

    def update(self) -> ArmyPlan:
        now = float(getattr(self.bot, "time", 0.0) or 0.0)
        scores, reasons = self._score_plans()
        self.last_scores = dict(scores)
        best = max(scores, key=lambda k: scores[k])
        cur = self.current_plan_name

        # Sticky hysteresis: do not switch just because one muta or one cannon was seen.
        can_switch = (now - self.last_switch_time) >= self.min_plan_duration
        meaningful_gain = scores[best] >= scores.get(cur, 0.0) + 1.75

        # Early bridge should be allowed to give way once real scouting data exists or game is midgame.
        if cur == "early_basic_roach_ling_bane" and (now >= 300 or scores[best] >= 4.0):
            meaningful_gain = scores[best] >= scores[cur] + 0.75

        if best != cur and can_switch and meaningful_gain:
            self.current_plan_name = best
            self.current_reason = reasons.get(best, "score switch")
            self.last_switch_time = now

        # v2.7: if a gas-heavy late plan was selected but made no realistic tech
        # progress for too long, do not keep the bot locked in a plan it cannot
        # execute.  Reset to a feasible midgame bridge; RL will be rewarded for
        # re-entering late tech once gas/tech are actually ready.
        try:
            current = PLANS[self.current_plan_name]
            age = now - float(self.last_switch_time)
            has_lair = self._own_has_any_structure("LAIR", "HIVE")
            has_pit = self._own_has_any_structure("INFESTATIONPIT")
            if current.requires_hive and age >= 190 and not (has_lair and has_pit):
                fallback = "hydra_lurker" if self._own_has_any_structure("HYDRALISKDEN") else "roach_ravager"
                self.current_plan_name = fallback
                self.current_reason = f"reset unreachable late plan after {age:.0f}s without lair+pit"
                self.last_switch_time = now
        except Exception:
            pass

        try:
            self.bot.rl_army_plan = self.current_plan_name
            self.bot.rl_army_plan_reason = self.current_reason
            self.bot.rl_army_plan_since = float(self.last_switch_time)
            self.bot.rl_army_plan_scores = dict(self.last_scores)
        except Exception:
            pass
        return PLANS[self.current_plan_name]

    def _own_has_any_structure(self, *names: str) -> bool:
        try:
            from sc2.ids.unit_typeid import UnitTypeId
            for name in names:
                uid = UnitTypeId.__members__.get(str(name).upper())
                if uid is not None and self.bot.structures(uid).exists:
                    return True
        except Exception:
            pass
        return False

    def _visible_enemy_snapshot(self) -> Dict[str, int | bool]:
        snap = {
            "army": 0,
            "air": 0,
            "capital_air": 0,
            "light_swarm": 0,
            "armored_ground": 0,
            "splash": 0,
            "static": 0,
            "workers": 0,
            "tech_air": False,
            "tech_turtle": False,
            "tech_hive_like": False,
            "anti_air_static": 0,
            "enemy_lurker": 0,
            "enemy_ultra": 0,
        }
        # v2.5: only COMBAT air should trigger anti-air plans.  In ZvZ, enemy
        # Overlords/Overseers are flying but are not an air army; counting every
        # flying unit made the selector over-pick anti_air_hydra_corruptor, which
        # explains the persistent roach+hydra / "双喷" bias in the summaries.
        air_names = {
            "MUTALISK", "CORRUPTOR", "BROODLORD", "PHOENIX", "VOIDRAY", "ORACLE", "TEMPEST",
            "CARRIER", "VIKINGFIGHTER", "BANSHEE", "BATTLECRUISER", "LIBERATOR", "RAVEN", "MEDIVAC",
        }
        noncombat_air = {
            "OVERLORD", "OVERLORDTRANSPORT", "OVERSEER", "OBSERVER", "WARPPRISM",
            "CHANGELING", "CHANGELINGZERGLING", "CHANGELINGZEALOT", "CHANGELINGMARINE",
            "CHANGELINGMARINESHIELD", "MULE", "LARVA", "EGG",
        }
        capital_air = {"BROODLORD", "CARRIER", "TEMPEST", "BATTLECRUISER"}
        light_names = {"ZERGLING", "BANELING", "ZEALOT", "ADEPT", "MARINE", "HELLION", "REAPER"}
        armored_ground = {
            "ROACH", "RAVAGER", "STALKER", "IMMORTAL", "MARAUDER", "SIEGETANK", "SIEGETANKSIEGED",
            "THOR", "ULTRALISK", "ARCHON", "COLOSSUS", "LURKERMP", "LURKER", "CYCLONE",
        }
        splash_names = {"BANELING", "SIEGETANK", "SIEGETANKSIEGED", "COLOSSUS", "DISRUPTOR", "HIGHTEMPLAR", "LURKERMP", "LURKER", "RAVEN", "ARCHON"}
        workers = {"DRONE", "PROBE", "SCV"}
        tech_air = {"SPIRE", "GREATERSPIRE", "STARGATE", "FLEETBEACON", "STARPORT", "FUSIONCORE"}
        tech_turtle = {"PHOTONCANNON", "SPINECRAWLER", "SPORECRAWLER", "BUNKER", "MISSILETURRET", "PLANETARYFORTRESS", "SIEGETANK", "SIEGETANKSIEGED"}
        tech_hive_like = {"HIVE", "INFESTATIONPIT", "TEMPLARARCHIVE", "ROBOTICSBAY", "FUSIONCORE", "GHOSTACADEMY"}
        static_aa = {"SPORECRAWLER", "PHOTONCANNON", "MISSILETURRET"}

        try:
            enemy_units = list(getattr(self.bot, "enemy_units", []) or [])
        except Exception:
            enemy_units = []
        for u in enemy_units:
            name = getattr(getattr(u, "type_id", None), "name", "")
            if not name:
                continue
            if name in workers:
                snap["workers"] += 1
                continue
            if getattr(u, "is_structure", False):
                continue
            # Non-combat scout/transport units are information, not army composition.
            if name in noncombat_air:
                continue
            snap["army"] += 1
            is_combat_air = (name in air_names) or (
                bool(getattr(u, "is_flying", False))
                and (bool(getattr(u, "can_attack_ground", False)) or bool(getattr(u, "can_attack_air", False)))
            )
            if is_combat_air:
                snap["air"] += 1
            if name in capital_air:
                snap["capital_air"] += 1
            if name in light_names:
                snap["light_swarm"] += 1
            if name in armored_ground:
                snap["armored_ground"] += 1
            if name in {"LURKERMP", "LURKER", "LURKERMPBURROWED", "LURKERBURROWED"}:
                snap["enemy_lurker"] += 1
            if name == "ULTRALISK":
                snap["enemy_ultra"] += 1
            if name in splash_names:
                snap["splash"] += 1
            if name in tech_turtle:
                snap["tech_turtle"] = True

        try:
            enemy_structures = list(getattr(self.bot, "enemy_structures", []) or [])
        except Exception:
            enemy_structures = []
        for s in enemy_structures:
            name = getattr(getattr(s, "type_id", None), "name", "")
            if not name:
                continue
            if name in tech_air:
                snap["tech_air"] = True
            if name in tech_turtle:
                snap["static"] += 1
                snap["tech_turtle"] = True
            if name in static_aa:
                snap["anti_air_static"] += 1
            if name in tech_hive_like:
                snap["tech_hive_like"] = True

        # Use remembered scout intel too.  Visible enemy structures often disappear
        # right before the bot needs to decide its transition; memory prevents "forgetting"
        # that we saw spire/stargate/starport/static/hive-like tech earlier.
        try:
            scout = getattr(self.bot, "scout", None)
            intel = getattr(scout, "intel", None)
            tech_seen = set(getattr(intel, "enemy_tech_seen", set()) or set())
            tech_text = " ".join(str(x).upper() for x in tech_seen)
            if any(k in tech_text for k in ["SPIRE", "STARGATE", "STARPORT", "FLEET", "FUSION"]):
                snap["tech_air"] = True
            if any(k in tech_text for k in ["CANNON", "BUNKER", "MISSILE", "PLANETARY", "SIEGE", "STATIC"]):
                snap["tech_turtle"] = True
            if any(k in tech_text for k in ["HIVE", "INFESTATION", "TEMPLAR", "ROBOTICSBAY", "FUSION", "GHOST"]):
                snap["tech_hive_like"] = True
        except Exception:
            pass
        return snap

    def _score_plans(self) -> tuple[Dict[str, float], Dict[str, str]]:
        t = float(getattr(self.bot, "time", 0.0) or 0.0)
        supply = float(getattr(self.bot, "supply_used", 0.0) or 0.0)
        bases = 0
        workers = 0
        minerals = float(getattr(self.bot, "minerals", 0.0) or 0.0)
        gas = float(getattr(self.bot, "vespene", 0.0) or 0.0)
        try:
            bases = int(getattr(self.bot, "townhalls", []).ready.amount)
        except Exception:
            pass
        try:
            workers = int(getattr(self.bot, "workers", []).amount)
        except Exception:
            pass
        snap = self._visible_enemy_snapshot()

        scores = {name: 0.0 for name in PLANS}
        reasons = {name: "" for name in PLANS}

        # Early bridge: only strong before 4-5min.  It must decay, otherwise the bot
        # keeps making early units forever and never learns a mid/late army identity.
        if t < 240:
            scores["early_basic_roach_ling_bane"] = 5.0
        elif t < 330:
            scores["early_basic_roach_ling_bane"] = 2.8
        elif t < 480:
            scores["early_basic_roach_ling_bane"] = 0.3
        else:
            scores["early_basic_roach_ling_bane"] = -1.4
        reasons["early_basic_roach_ling_bane"] = "early bridge; decays after midgame so RL must scout/transition"

        # Enemy air / air tech -> hydra/corruptor, unless we are already in a brood game.
        air_signal = int(snap["air"]) + (4 if snap["tech_air"] else 0) + int(snap["capital_air"]) * 2
        scores["anti_air_hydra_corruptor"] += air_signal * 1.25
        if air_signal:
            reasons["anti_air_hydra_corruptor"] = f"enemy air/air-tech signal={air_signal}"

        # Heavy armored ground -> roach/ravager early, lurker later.
        armored = int(snap["armored_ground"])
        if armored:
            scores["roach_ravager"] += min(8.0, armored * 0.75) + (2.0 if t < 520 else 0.0)
            scores["hydra_lurker"] += min(8.0, armored * 0.55) + (2.0 if t >= 430 or bases >= 3 else 0.0)
            reasons["roach_ravager"] = f"enemy armored ground={armored}, midgame roach/ravager is stable"
            reasons["hydra_lurker"] = f"enemy armored/deathball={armored}, transition to hydra-lurker"

        # Light/bio/swarm -> ling-bane then ultra-ling-bane.
        light = int(snap["light_swarm"])
        if light >= 6:
            scores["ultra_ling_bane"] += min(9.0, light * 0.55) + (2.0 if t >= 520 or supply >= 130 else -1.5)
            scores["early_basic_roach_ling_bane"] += min(4.0, light * 0.25)
            reasons["ultra_ling_bane"] = f"mass light/bio/swarm={light}, late answer is ultra-ling-bane"

        # Turtle / many static / splash / enemy lurker -> siege tech.  Enemy lurkers are
        # especially important: roach-hydra walking into lurker lines is exactly the failure
        # the user reported.  One observed lurker is enough to start valuing own lurker tech;
        # repeated/static/hive evidence can justify brood-viper later.
        static = int(snap["static"])
        splash = int(snap["splash"])
        enemy_lurker = int(snap.get("enemy_lurker", 0))
        turtle_signal = static + splash + 2 * enemy_lurker + (3 if snap["tech_turtle"] else 0)
        brood_evidence = turtle_signal >= 5 or enemy_lurker >= 2 or int(snap["capital_air"]) > 0 or bool(snap["tech_hive_like"])
        if turtle_signal >= 2:
            scores["hydra_lurker"] += 3.0 + min(8.0, turtle_signal * 0.85)
            reasons["hydra_lurker"] = f"enemy lurker/static/splash signal={turtle_signal}; stop pure roach-hydra and set up lurkers"
            if brood_evidence and (t >= 560 or supply >= 160 or bases >= 5):
                scores["brood_corruptor_viper"] += 2.5 + min(8.0, turtle_signal * 0.70)
                reasons["brood_corruptor_viper"] = f"strong late siege evidence={turtle_signal}, brood-corruptor-viper is justified"

        # Greedy / low anti-air scouting window can justify muta-ling-bane.
        low_aa = int(snap["anti_air_static"]) == 0 and not bool(snap["tech_air"])
        if t >= 300 and bases >= 3 and workers >= 45 and low_aa and int(snap["air"]) <= 1 and int(snap["static"]) <= 2:
            scores["ling_bane_muta"] += 3.5 + (1.0 if minerals >= 400 and gas >= 150 else 0.0)
            reasons["ling_bane_muta"] = "3-base economy with low observed anti-air: muta-ling-bane punish is plausible"

        # Hive-like enemy tech means we should also value our own late plans.
        if bool(snap["tech_hive_like"]):
            scores["hydra_lurker"] += 2.0
            scores["brood_corruptor_viper"] += 2.5 if t >= 520 else 0.5
            scores["ultra_ling_bane"] += 1.5 if light >= 4 else 0.0

        # Own economy has reached a transition window.  This does NOT prescribe a
        # fixed route; it amplifies the plan that current evidence already supports.
        if t >= 600 or supply >= 180:
            if air_signal >= 3 or int(snap["capital_air"]) > 0:
                scores["anti_air_hydra_corruptor"] += 2.5
                if bases >= 4:
                    scores["brood_corruptor_viper"] += 1.8
            if turtle_signal >= 3:
                scores["hydra_lurker"] += 1.4
                if turtle_signal >= 5 or int(snap["capital_air"]) > 0 or bool(snap["tech_hive_like"]):
                    scores["brood_corruptor_viper"] += 1.8
            if light >= 8:
                scores["ultra_ling_bane"] += 2.2
            if armored >= 6 or splash >= 3:
                scores["hydra_lurker"] += 2.0
            if int(snap["army"]) >= 4 and max(air_signal, turtle_signal, light, armored, splash) <= 2:
                scores["roach_ravager"] += 0.8
                reasons["roach_ravager"] = "low-specificity enemy army seen; keep stable midgame core while scouting"

        # v2.9: no-intel transition fallback.  The old selector was too honest: if
        # scouting was weak it could stay on the early bridge / roach-ravager forever,
        # which is exactly why it walked roach/hydra into lurker/static lines and never
        # reached Hive tech.  A real bot still needs a default mid/late route when it
        # has 3+ bases but incomplete information.
        low_specificity = max(air_signal, turtle_signal, light, armored, splash) <= 2
        if low_specificity and bases >= 3 and (workers >= 45 or supply >= 105) and t >= 420:
            scores["hydra_lurker"] += 3.2
            reasons["hydra_lurker"] = "default 3-base midgame transition under low scouting: hydra-lurker tech cannot be skipped"
        if low_specificity and bases >= 4 and (workers >= 62 or supply >= 155) and t >= 620:
            scores["hydra_lurker"] += 1.8
            scores["brood_corruptor_viper"] += 2.4
            reasons["brood_corruptor_viper"] = "default 4-base late transition under low scouting: prepare brood/corruptor/viper option"
        if low_specificity and bases >= 4 and (workers >= 62 or supply >= 150) and t >= 640 and light >= 4:
            scores["ultra_ling_bane"] += 2.2
            reasons["ultra_ling_bane"] = "late anti-light fallback: ultra-ling-bane option"

        # Feasibility: do not pick gas-heavy late plans when economy cannot support them.
        if bases < 3 or workers < 42:
            for n in ["ling_bane_muta", "hydra_lurker", "anti_air_hydra_corruptor", "ultra_ling_bane", "brood_corruptor_viper"]:
                scores[n] -= 2.0
        if bases < 4 or workers < 58:
            scores["brood_corruptor_viper"] -= 3.5
            scores["ultra_ling_bane"] -= 2.5
        if bases < 5 and t < 650:
            scores["brood_corruptor_viper"] -= 1.5
        # If we have not even started the Lair/Pit chain, brood/ultra is an expensive
        # aspiration, not the current army identity.  Keep it learnable, but make the
        # selector prefer a reachable bridge until tech execution catches up.
        try:
            has_lair = self._own_has_any_structure("LAIR", "HIVE")
            has_pit = self._own_has_any_structure("INFESTATIONPIT")
            if not has_lair and t < 620:
                scores["brood_corruptor_viper"] -= 2.0
                scores["ultra_ling_bane"] -= 1.5
            if not has_pit and t < 700:
                scores["brood_corruptor_viper"] -= 1.2
                scores["ultra_ling_bane"] -= 1.0
        except Exception:
            pass

        # Keep current plan slightly preferred to reduce thrashing.
        scores[self.current_plan_name] = scores.get(self.current_plan_name, 0.0) + 1.0
        return scores, reasons


UNIT_TO_PRIMITIVE = {
    "ZERGLING": "MAKE_ZERGLING",
    "BANELING": "MORPH_BANELING",
    "ROACH": "MAKE_ROACH",
    "RAVAGER": "MORPH_RAVAGER",
    "HYDRALISK": "MAKE_HYDRALISK",
    "LURKER": "MORPH_LURKER",
    "MUTALISK": "MAKE_MUTALISK",
    "CORRUPTOR": "MAKE_CORRUPTOR",
    "BROODLORD": "MAKE_BROODLORD",
    "INFESTOR": "MAKE_INFESTOR",
    "VIPER": "MAKE_VIPER",
    "ULTRALISK": "MAKE_ULTRALISK",
    "OVERSEER": "MORPH_OVERSEER",
}


UNIT_COUNT_FEATURE = {
    "ZERGLING": "zergling_count",
    "BANELING": "baneling_count",
    "ROACH": "roach_count",
    "RAVAGER": "ravager_count",
    "HYDRALISK": "hydra_count",
    "LURKER": "lurker_count",
    "MUTALISK": "mutalisk_count",
    "CORRUPTOR": "corruptor_count",
    "BROODLORD": "broodlord_count",
    "INFESTOR": "infestor_count",
    "VIPER": "viper_count",
    "ULTRALISK": "ultralisk_count",
    "OVERSEER": "overseer_count",
}
