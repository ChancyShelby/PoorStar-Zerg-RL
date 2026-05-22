# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Iterable, List

from poorstar.executor.action_executor import ActionResult
from rl_v1.tech_intent import ArmyPlan, TechIntentSelector, UNIT_COUNT_FEATURE, UNIT_TO_PRIMITIVE


class MacroAction(IntEnum):
    """Macro-RL strategic intents.

    v2.4 key change: tech / unit production are task-driven and stage-shaped.
    The RL policy still chooses high-level intents, but state features + reward
    teach it the match rhythm: economy -> plan setup -> timing -> late transition -> map hunt.
    """

    DO_NOTHING = 0
    ECON_MACRO = 1
    LING_PRESSURE = 2
    ROACH_PRESSURE = 3
    ROACH_HYDRA_TIMING = 4
    FAST_LAIR_TECH = 5
    FAST_HIVE_TECH = 6
    UPGRADE_FOCUS = 7
    SCOUT_FOCUS = 8
    DEFENSIVE_HOLD = 9
    MAXED_ATTACK = 10


ACTION_NAMES: List[str] = [a.name for a in MacroAction]
ACTION_DIM = len(ACTION_NAMES)


@dataclass
class MacroExecution:
    ok: bool
    macro_action: str
    primitive_action: str = ""
    reason: str = ""
    consumed_turn: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "macro_action": self.macro_action,
            "primitive_action": self.primitive_action,
            "reason": self.reason,
            "consumed_turn": self.consumed_turn,
        }


def _obs(bot) -> Dict[str, float]:
    from rl_v1.state_features import extract_observation
    return extract_observation(bot)


class MacroActionExecutor:
    """Translate RL strategic intents into baseline primitives.

    The central invariant is composition coherence:
    - early basic roach/ling/bane is allowed as the cheap bridge;
    - after scouting, exactly one main army plan is sticky for at least ~75s;
    - tech/upgrades/production serve that plan only;
    - support units have caps, so the bot does not make "a little bit of everything".
    """

    def __init__(self, bot):
        self.bot = bot
        self.last_scout_intent_time = -999.0
        self.last_attack_intent_time = -999.0
        self.tech_selector = TechIntentSelector(bot)

    @staticmethod
    def _gas_emergency(o: Dict[str, float], plan: ArmyPlan) -> bool:
        t = float(o.get("game_time", 0.0) or 0.0)
        minerals = float(o.get("minerals", 0.0) or 0.0)
        gas = float(o.get("vespene", 0.0) or 0.0)
        supply = float(o.get("supply_used", 0.0) or 0.0)
        plan_target = float(getattr(plan, "gas_target", 2) or 2)
        if t >= 300 and minerals >= 1200 and gas <= 250:
            return True
        if t >= 420 and minerals >= 1800 and gas <= 420:
            return True
        if t >= 540 and minerals >= 2500 and gas <= 700:
            return True
        if supply >= 135 and plan_target >= 6 and minerals >= 1000 and gas <= 350:
            return True
        return False

    async def _fix_gas_economy(self, macro_name: str, plan: ArmyPlan, reason: str = "") -> MacroExecution:
        """Baseline gas repair used by many intents.

        This is deliberately below the RL strategy level: the policy can choose a plan,
        but the executor must create the material conditions for that plan.  Without
        this, it learns the broken loop: roach/hydra forever with 9000 minerals / 34 gas.
        """
        o = _obs(self.bot)
        desired = self._desired_gas_count(o, plan)
        total = float(o.get("total_gas_count", 0.0) or 0.0)
        ready = float(o.get("ready_gas_count", 0.0) or 0.0)
        minerals = float(o.get("minerals", 0.0) or 0.0)
        gas_workers = float(o.get("gas_worker_count", ready * 3.0) or 0.0)
        if total < desired and minerals >= 75:
            res = await self._try_actions(macro_name, ["BUILD_GAS"])
            if res.ok:
                res.reason = f"gas economy repair: need {total:.0f}/{desired} extractors; {reason}; {res.reason}"
                return res
        if ready > 0 and gas_workers < min(ready, desired) * 3:
            res = await self._try_actions(macro_name, ["ASSIGN_GAS_WORKERS"])
            if res.ok:
                res.reason = f"gas economy repair: gas_workers={gas_workers:.0f}/{min(ready, desired)*3:.0f}; {reason}; {res.reason}"
                return res
        return MacroExecution(False, macro_name, "", f"gas repair unavailable: desired={desired}, total={total}, ready={ready}, minerals={minerals}", consumed_turn=False)

    async def execute(self, action_idx: int) -> MacroExecution:
        action = MacroAction(int(action_idx))
        name = action.name

        try:
            self.bot.rl_current_intent = name
            self.bot.rl_current_intent_time = float(getattr(self.bot, "time", 0.0))
        except Exception:
            pass

        # Update once per RL decision.  All branches below use the same plan.
        plan = self._current_plan()

        # v2.8 hard baseline guard: when the economy is in gas emergency, almost any
        # strategic intent must first repair gas infrastructure/saturation.  Defense is
        # allowed to bypass this only under real worker-line pressure.
        try:
            o0 = _obs(self.bot)
            if self._gas_emergency(o0, plan) and action not in {MacroAction.DEFENSIVE_HOLD, MacroAction.MAXED_ATTACK}:
                repair = await self._fix_gas_economy(name, plan, reason="pre-intent emergency guard")
                if repair.ok:
                    return repair
        except Exception:
            pass

        if action == MacroAction.DO_NOTHING:
            return await self._do_nothing_fallback(name, plan)
        if action == MacroAction.ECON_MACRO:
            return await self._econ_macro(name, plan)
        if action == MacroAction.LING_PRESSURE:
            return await self._ling_pressure(name, plan)
        if action == MacroAction.ROACH_PRESSURE:
            return await self._roach_pressure(name, plan)
        if action == MacroAction.ROACH_HYDRA_TIMING:
            return await self._army_plan_timing(name, plan)
        if action == MacroAction.FAST_LAIR_TECH:
            return await self._plan_lair_tech(name, plan)
        if action == MacroAction.FAST_HIVE_TECH:
            return await self._plan_hive_tech(name, plan)
        if action == MacroAction.UPGRADE_FOCUS:
            return await self._upgrade_focus(name, plan)
        if action == MacroAction.SCOUT_FOCUS:
            return await self._scout_focus(name)
        if action == MacroAction.DEFENSIVE_HOLD:
            return await self._defensive_hold(name, plan)
        if action == MacroAction.MAXED_ATTACK:
            return await self._maxed_attack(name)
        return MacroExecution(False, name, "", "unknown strategic intent", consumed_turn=False)

    # -----------------------------------------------------------------------------------------
    # Intent executors
    # -----------------------------------------------------------------------------------------

    async def _do_nothing_fallback(self, name: str, plan: ArmyPlan) -> MacroExecution:
        """Do not let the learned policy waste critical turns with a literal wait.

        The RL reward still punishes DO_NOTHING in bad stages, but the executor converts
        it into a sane fallback so one unlucky sampled action does not ruin the game.
        This keeps exploration possible without teaching the bot to stare at 200/200.
        """
        o = _obs(self.bot)
        stage = "plan_production"
        try:
            from rl_v1.strategic_stage import infer_stage
            stage = infer_stage(o)
        except Exception:
            pass

        if stage == "defense" or o.get("early_allin_danger", 0.0) > 0.5 or o.get("visible_threats_worker_line", 0.0) >= 1:
            res = await self._defensive_hold(name, plan)
            if res.ok:
                res.reason = f"DO_NOTHING converted to defense; {res.reason}"
                return res
        if stage in {"timing_attack", "map_hunt"} or (o["supply_used"] >= 190 and o["army_supply"] >= 80):
            res = await self._attack_intent(name, min_army_units=30, reason=f"DO_NOTHING converted: stage={stage}")
            if res.ok:
                return res
        if stage in {"late_transition", "plan_setup"} or o.get("plan_stuck", 0.0) > 0.5 or o.get("plan_unrealized", 0.0) > 0.5:
            if plan.requires_hive or o.get("late_transition_due", 0.0) > 0.5:
                res = await self._plan_hive_tech(name, plan)
            else:
                res = await self._plan_lair_tech(name, plan)
            if res.ok:
                res.reason = f"DO_NOTHING converted to plan setup; {res.reason}"
                return res
        if o.get("spend_bank_urgency", 0.0) >= 0.7 or o.get("bank_too_high", 0.0) > 0.5:
            prod = await self._try_produce_for_plan(name, plan)
            if prod.ok:
                prod.reason = f"DO_NOTHING converted to spend bank; {prod.reason}"
                return prod
        return MacroExecution(True, name, "WAIT", f"low-pressure no-op; current_army_plan={plan.name}", consumed_turn=False)

    async def _econ_macro(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        if o["supply_left"] <= 2 and o["supply_used"] < 196:
            res = await self._try_actions(name, ["MAKE_OVERLORD"])
            if res.ok:
                return res

        if self._gas_emergency(o, plan):
            res = await self._fix_gas_economy(name, plan, reason="ECON_MACRO gas emergency")
            if res.ok:
                return res

        # If we are already in a real timing/maxed window, ECON_MACRO must not keep
        # idling at 200 supply.  Let RL learn that choosing ECON here gives less reward,
        # but also provide a sane executable fallback when it does choose ECON.
        if o.get("timing_attack_due", 0.0) > 0.5 and o["supply_used"] >= 190 and o["army_supply"] >= 90:
            res = await self._attack_intent(name, min_army_units=35, reason="ECON_MACRO converted: timing_attack_due at near max")
            if res.ok:
                return res

        # Base debt comes before filling worker count.  This protects 3rd/4th timing.
        if o["expand_debt"] > 0.5 and o["minerals"] >= 300:
            res = await self._try_actions(name, ["EXPAND"])
            if res.ok:
                return res

        # If current plan is clearly not being realized, fix gas/tech before more drones.
        if o.get("plan_stuck", 0.0) > 0.5 or o.get("plan_unrealized", 0.0) > 0.5:
            setup = await (self._plan_hive_tech(name, plan) if plan.requires_hive else self._plan_lair_tech(name, plan))
            if setup.ok:
                return setup

        # v2.4: workers have a strategic cap.  Do not keep droning to 87/70 just because
        # the raw ideal_worker_total looks large.  The cap depends on plan, bases and stage.
        worker_cap = max(o.get("worker_floor", 0.0), min(o.get("worker_target_cap", 82.0), 84.0))
        ideal_cap = max(o.get("worker_floor", 0.0), min(worker_cap, o.get("ideal_worker_total", worker_cap) or worker_cap))
        if o["worker_count"] < ideal_cap and o.get("worker_excess", 0.0) <= 0.0:
            res = await self._try_actions(name, ["MAKE_DRONE"])
            if res.ok:
                return res

        # Gas is plan-driven.  It supports the selected army plan, not random tech-tree climbing.
        if self._desired_gas_count(o, plan) > o["total_gas_count"] and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        if o.get("ready_gas_count", 0.0) > 0 and o.get("gas_worker_count", 0.0) < min(o.get("ready_gas_count", 0.0), self._desired_gas_count(o, plan)) * 3:
            res = await self._try_actions(name, ["ASSIGN_GAS_WORKERS"])
            if res.ok:
                return res

        # Plan setup: only build tech/upgrades required by the current selected composition.
        if o.get("plan_setup_due", 0.0) > 0.5 or o.get("spend_bank_urgency", 0.0) < 0.8:
            tech = await self._try_plan_tech(name, plan)
            if tech.ok:
                return tech
            upgrades = await self._try_plan_upgrades(name, plan)
            if upgrades.ok:
                return upgrades

        # If bank is high or army is below the time curve, spend larvae on the current plan.
        army_floor = max(22.0, min(115.0, o["game_time"] / 7.0))
        if o.get("spend_bank_urgency", 0.0) > 0.25 or o["army_supply"] < army_floor:
            prod = await self._try_produce_for_plan(name, plan)
            if prod.ok:
                return prod

        return MacroExecution(True, name, "WAIT", f"econ macro idle; plan={plan.name}; worker_cap={worker_cap:.0f}; fallback allowed", consumed_turn=False)

    async def _ling_pressure(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        self._set_scout_intent("economy")

        if o["supply_left"] <= 2 and o["supply_used"] < 196:
            res = await self._try_actions(name, ["MAKE_OVERLORD"])
            if res.ok:
                return res
        if o["ready_gas_count"] < 1 and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        if o["has_ling_speed"] < 0.5 and o["vespene"] >= 80:
            res = await self._try_actions(name, ["RESEARCH_ZERGLING_SPEED"])
            if res.ok:
                return res

        # Ling pressure is only coherent before the selected plan has become a late-game plan.
        if plan.name not in {"early_basic_roach_ling_bane", "ling_bane_muta", "ultra_ling_bane"} and o["game_time"] >= 300:
            return await self._army_plan_timing(name, plan)

        if (o.get("zergling_count", 0.0) >= 18 or o["army_supply"] >= 24 or o["supply_used"] >= 60) and o["game_time"] >= 210:
            res = await self._attack_intent(name, min_army_units=12, reason="LING_PRESSURE timing")
            if res.ok:
                return res
        res = await self._try_actions(name, ["MAKE_ZERGLING", "BUILD_BANELING_NEST", "MORPH_BANELING"])
        if res.ok:
            return res
        if o["worker_count"] < 32:
            res = await self._try_actions(name, ["MAKE_DRONE"])
            if res.ok:
                return res
        return MacroExecution(False, name, "", "LING_PRESSURE: no executable primitive", consumed_turn=False)

    async def _roach_pressure(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        self._set_scout_intent("army")
        if o["supply_left"] <= 2 and o["supply_used"] < 196:
            res = await self._try_actions(name, ["MAKE_OVERLORD"])
            if res.ok:
                return res
        if o["ready_gas_count"] < 2 and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        if o["has_roach_warren"] < 0.5:
            res = await self._try_actions(name, ["BUILD_ROACH_WARREN"])
            if res.ok:
                return res
        if o["game_time"] >= 260 and o["has_lair"] < 0.5 and o["vespene"] >= 90:
            res = await self._try_actions(name, ["MORPH_LAIR"])
            if res.ok:
                return res

        if plan.name not in {"early_basic_roach_ling_bane", "roach_ravager"} and o["game_time"] >= 360:
            return await self._army_plan_timing(name, plan)

        if o["roach_count"] >= 10 or o["army_supply"] >= 45:
            res = await self._attack_intent(name, min_army_units=18, reason="ROACH_PRESSURE timing")
            if res.ok:
                return res
        res = await self._try_actions(name, ["MAKE_ROACH", "MORPH_RAVAGER", "RESEARCH_ROACH_SPEED", "MAKE_ZERGLING"])
        if res.ok:
            return res
        return MacroExecution(False, name, "", "ROACH_PRESSURE: no executable primitive", consumed_turn=False)

    async def _army_plan_timing(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        self._set_scout_intent("army")
        if o["supply_left"] <= 3 and o["supply_used"] < 196:
            res = await self._try_actions(name, ["MAKE_OVERLORD"])
            if res.ok:
                return res

        # Attack is checked early.  The previous version often kept taking upgrades at
        # 180-200 supply and missed the real timing window.
        if o.get("timing_attack_due", 0.0) > 0.5 or (o["army_supply"] >= 95 and o["supply_used"] >= 175):
            res = await self._attack_intent(name, min_army_units=22, reason=f"{name}: stage timing_attack for plan={plan.name}")
            if res.ok:
                return res

        gas_target = self._desired_gas_count(o, plan)
        if o["total_gas_count"] < gas_target and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        tech = await self._try_plan_tech(name, plan)
        if tech.ok:
            return tech
        upgrades = await self._try_plan_upgrades(name, plan)
        if upgrades.ok:
            return upgrades

        prod = await self._try_produce_for_plan(name, plan)
        if prod.ok:
            return prod

        # Secondary attack fallback if production cannot spend and army is already sizeable.
        if o["army_supply"] >= 70 or o["supply_used"] >= 150:
            res = await self._attack_intent(name, min_army_units=22, reason=f"{name}: production blocked, use existing army plan={plan.name}")
            if res.ok:
                return res
        return MacroExecution(False, name, "", f"{name}: no executable primitive for plan={plan.name}", consumed_turn=False)

    async def _plan_lair_tech(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        if self._desired_gas_count(o, plan) > o["total_gas_count"] and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        if o.get("ready_gas_count", 0.0) > 0 and o.get("gas_worker_count", 0.0) < min(o.get("ready_gas_count", 0.0), self._desired_gas_count(o, plan)) * 3:
            res = await self._try_actions(name, ["ASSIGN_GAS_WORKERS"])
            if res.ok:
                return res
        if plan.requires_lair and o["has_lair"] < 0.5:
            res = await self._try_actions(name, ["MORPH_LAIR"])
            if res.ok:
                return res
        # For Hive plans, FAST_LAIR_TECH is still a setup action; after Lair, keep
        # walking the required chain instead of falling into random production.
        if plan.requires_hive:
            res = await self._plan_hive_tech(name, plan)
            if res.ok:
                return res
        tech = await self._try_plan_tech(name, plan)
        if tech.ok:
            return tech
        prod = await self._try_produce_for_plan(name, plan)
        if prod.ok:
            return prod
        return MacroExecution(False, name, "", f"FAST_LAIR_TECH: plan={plan.name} has no executable lair primitive", consumed_turn=False)

    async def _plan_hive_tech(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        self._set_scout_intent("tech")
        if self._desired_gas_count(o, plan) > o["total_gas_count"] and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        if o.get("ready_gas_count", 0.0) > 0 and o.get("gas_worker_count", 0.0) < min(o.get("ready_gas_count", 0.0), self._desired_gas_count(o, plan)) * 3:
            res = await self._try_actions(name, ["ASSIGN_GAS_WORKERS"])
            if res.ok:
                return res

        # Required tech chain: ordered, inspectable, and derived from the selected plan.
        # It is not a default route; it only runs for the current plan.
        chain = self._required_tech_chain(plan)
        if chain:
            tech = await self._try_actions(name, chain)
            if tech.ok:
                tech.reason = f"plan setup chain for {plan.name}; {tech.reason}"
                return tech

        upgrades = await self._try_plan_upgrades(name, plan)
        if upgrades.ok:
            return upgrades
        prod = await self._try_produce_for_plan(name, plan)
        if prod.ok:
            return prod
        return MacroExecution(False, name, "", f"FAST_HIVE_TECH: plan={plan.name}; no executable plan-chain primitive", consumed_turn=False)

    async def _upgrade_focus(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        if self._desired_gas_count(o, plan) > o["total_gas_count"] and o["minerals"] >= 75:
            res = await self._try_actions(name, ["BUILD_GAS"])
            if res.ok:
                return res
        if o.get("ready_gas_count", 0.0) > 0 and o.get("gas_worker_count", 0.0) < min(o.get("ready_gas_count", 0.0), self._desired_gas_count(o, plan)) * 3:
            res = await self._try_actions(name, ["ASSIGN_GAS_WORKERS"])
            if res.ok:
                return res
        upgrades = await self._try_plan_upgrades(name, plan)
        if upgrades.ok:
            return upgrades
        return MacroExecution(False, name, "", f"UPGRADE_FOCUS: no pending upgrade for plan={plan.name}", consumed_turn=False)

    async def _scout_focus(self, name: str) -> MacroExecution:
        o = _obs(self.bot)
        plan = self._current_plan()

        # v2.9: scouting is useful, but it must not eat the turns where we are
        # supply-blocked, gas-dead, plan-stuck or sitting on a huge bank.
        # In those cases, set the scout intent but execute a productive fallback.
        urgent_macro = (
            o.get("gas_economy_emergency", 0.0) > 0.5
            or o.get("gas_worker_debt", 0.0) >= 6
            or o.get("plan_stuck", 0.0) > 0.5
            or o.get("plan_unrealized", 0.0) > 0.5
            or o.get("spend_bank_urgency", 0.0) >= 0.7
            or o.get("timing_attack_due", 0.0) > 0.5
        )

        if o["enemy_nat_seen"] < 0.5 or o["enemy_third_seen"] < 0.5:
            self._set_scout_intent("economy")
        elif o["enemy_tech_seen_count"] < 2 or o.get("scout_info_age", 999.0) > 60:
            self._set_scout_intent("tech")
        else:
            self._set_scout_intent("army")

        if urgent_macro:
            if o.get("timing_attack_due", 0.0) > 0.5 and o.get("army_supply", 0.0) >= 50:
                res = await self._attack_intent(name, min_army_units=22, reason="SCOUT_FOCUS converted: timing attack due")
                if res.ok:
                    return res
            prod = await self._try_produce_for_plan(name, plan)
            if prod.ok:
                prod.reason = f"SCOUT_FOCUS converted to productive fallback; {prod.reason}"
                return prod
            setup = await (self._plan_hive_tech(name, plan) if plan.requires_hive else self._plan_lair_tech(name, plan))
            if setup.ok:
                setup.reason = f"SCOUT_FOCUS converted to plan setup; {setup.reason}"
                return setup

        res = await self._try_actions(name, ["MORPH_OVERSEER", "MAKE_OVERLORD"])
        if res.ok:
            return res
        return MacroExecution(True, name, "SCOUT_INTENT", f"set scout intent={getattr(self.bot, 'rl_scout_intent', '')}", consumed_turn=False)

    async def _defensive_hold(self, name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)
        res = await self._defend_intent(name)
        if res.ok:
            return res

        # v2.5: anti-all-in emergency production is NOT the same as the long-term
        # army plan.  Under early pressure, do not try to build Hydralisk Den/Spire
        # just because the selected plan says so; make cheap units, queens, roaches,
        # banelings and a spine if possible.
        if o.get("early_allin_danger", 0.0) > 0.5:
            if o["supply_left"] <= 2 and o["supply_used"] < 196:
                res = await self._try_actions(name, ["MAKE_OVERLORD"])
                if res.ok:
                    return res
            emergency = [
                "MAKE_QUEEN",
                "MORPH_BANELING",
                "MAKE_ROACH",
                "MAKE_ZERGLING",
                "BUILD_ROACH_WARREN",
                "BUILD_BANELING_NEST",
                "BUILD_SPINE",
            ]
            res = await self._try_actions(name, emergency)
            if res.ok:
                res.reason = f"anti-all-in emergency; {res.reason}"
                return res

        if o["enemy_air_seen"] > 0.5:
            res = await self._try_actions(name, ["MAKE_HYDRALISK", "MAKE_CORRUPTOR", "MORPH_OVERSEER", "BUILD_SPORE"])
            if res.ok:
                return res
        prod = await self._try_produce_for_plan(name, plan)
        if prod.ok:
            return prod
        return MacroExecution(False, name, "", "DEFENSIVE_HOLD: could not defend or produce plan units", consumed_turn=False)

    async def _maxed_attack(self, name: str) -> MacroExecution:
        o = _obs(self.bot)
        if o["army_supply"] >= 42 or o["supply_used"] >= 135:
            res = await self._attack_intent(name, min_army_units=20, reason="MAXED_ATTACK strategic intent")
            if res.ok:
                return res
        return MacroExecution(False, name, "ATTACK_MOVE", "not enough army for MAXED_ATTACK", consumed_turn=False)

    # -----------------------------------------------------------------------------------------
    # Plan helpers
    # -----------------------------------------------------------------------------------------

    def _current_plan(self) -> ArmyPlan:
        return self.tech_selector.current_plan()

    def _required_tech_chain(self, plan: ArmyPlan) -> List[str]:
        """Return ordered tech prerequisites for the selected composition.

        The executor can call the whole chain repeatedly: completed items fail cleanly
        and the next missing prerequisite is attempted.
        """
        name = str(plan.name)
        if name == "brood_corruptor_viper":
            return ["MORPH_LAIR", "BUILD_SPIRE", "BUILD_INFESTATION_PIT", "MORPH_HIVE", "BUILD_GREATER_SPIRE"]
        if name == "ultra_ling_bane":
            return ["MORPH_LAIR", "BUILD_BANELING_NEST", "BUILD_INFESTATION_PIT", "MORPH_HIVE", "BUILD_ULTRALISK_CAVERN"]
        if name == "hydra_lurker":
            return ["MORPH_LAIR", "BUILD_HYDRA_DEN", "BUILD_LURKER_DEN"]
        if name == "anti_air_hydra_corruptor":
            return ["MORPH_LAIR", "BUILD_HYDRA_DEN", "BUILD_SPIRE"]
        if name == "ling_bane_muta":
            return ["MORPH_LAIR", "BUILD_BANELING_NEST", "BUILD_SPIRE"]
        if name == "roach_ravager":
            return ["BUILD_ROACH_WARREN", "MORPH_LAIR"]
        return list(plan.tech or [])

    async def _try_plan_tech(self, macro_name: str, plan: ArmyPlan) -> MacroExecution:
        tech_chain = self._required_tech_chain(plan)
        if not tech_chain:
            return MacroExecution(False, macro_name, "", f"plan={plan.name} has no tech list", consumed_turn=False)
        res = await self._try_actions(macro_name, tech_chain)
        if res.ok:
            res.reason = f"plan={plan.name}; {res.reason}"
            return res
        return MacroExecution(False, macro_name, "", f"plan tech failed for {plan.name}: {res.reason}", consumed_turn=False)

    async def _try_plan_upgrades(self, macro_name: str, plan: ArmyPlan) -> MacroExecution:
        if not plan.upgrades:
            return MacroExecution(False, macro_name, "", f"plan={plan.name} has no upgrade list", consumed_turn=False)
        res = await self._try_actions(macro_name, list(plan.upgrades))
        if res.ok:
            res.reason = f"plan={plan.name}; {res.reason}"
            return res
        return MacroExecution(False, macro_name, "", f"plan upgrades failed for {plan.name}: {res.reason}", consumed_turn=False)

    def _unit_count(self, unit_name: str, obs: Dict[str, float]) -> int:
        key = UNIT_COUNT_FEATURE.get(unit_name)
        if key and key in obs:
            return int(obs.get(key, 0.0) or 0)
        # Fallback for overseer or newly added unit names.
        try:
            from sc2.ids.unit_typeid import UnitTypeId
            uid = UnitTypeId.__members__.get(unit_name)
            if uid is not None:
                return int(self.bot.units(uid).amount)
        except Exception:
            pass
        return 0

    async def _try_produce_for_plan(self, macro_name: str, plan: ArmyPlan) -> MacroExecution:
        o = _obs(self.bot)

        # Do not sink the last gas into midgame units when the selected plan needs gas-heavy
        # tech.  First create/saturate gas; otherwise brood/ultra/lurker/viper never happen.
        if self._gas_emergency(o, plan):
            gas_fix = await self._fix_gas_economy(macro_name, plan, reason=f"before production for plan={plan.name}")
            if gas_fix.ok:
                return gas_fix
            if plan.gas_target >= 6 and o.get("vespene", 0.0) < 350:
                return MacroExecution(False, macro_name, "", f"production delayed: gas emergency for plan={plan.name}", consumed_turn=False)

        # Make sure the required tech exists before production.  This is cheap to call:
        # executor returns clean failures when already built/pending.
        tech = await self._try_plan_tech(macro_name, plan)
        if tech.ok:
            return tech
        # If a plan is late-tech and its core prerequisites are still missing, do not
        # pretend hydras/roaches are realizing a brood/ultra plan.  Let the action fail
        # so reward/mask learn to choose setup instead.
        if plan.requires_hive and o.get("has_hive", 0.0) < 0.5 and o.get("plan_stuck", 0.0) > 0.5:
            return MacroExecution(False, macro_name, "", f"production blocked: plan={plan.name} needs Hive/tech first", consumed_turn=False)

        weights = dict(plan.unit_weights or {})
        if not weights:
            primitives = [UNIT_TO_PRIMITIVE[u] for u in plan.main_units if u in UNIT_TO_PRIMITIVE]
            return await self._try_actions(macro_name, primitives)

        counts = {u: self._unit_count(u, o) for u in weights}
        total = max(1, sum(counts.values()))

        # Stage 1: establish main army identity.  Before any support scatter, make sure
        # at least one main unit line is actually present.
        main_existing = sum(counts.get(u, 0) for u in plan.main_units)
        if main_existing <= 0:
            primitives = [UNIT_TO_PRIMITIVE[u] for u in plan.main_units if u in UNIT_TO_PRIMITIVE]
            res = await self._try_actions(macro_name, primitives)
            if res.ok:
                res.reason = f"establish main army plan={plan.name}; {res.reason}"
                return res

        deficits = []
        for unit, weight in weights.items():
            if unit in plan.support_caps and counts.get(unit, 0) >= plan.support_caps[unit]:
                continue
            desired = max(1, int(round(total * float(weight))))
            actual = int(counts.get(unit, 0))
            # Support units need stronger deficit before production; this prevents a little bit of everything.
            threshold = 0.75 if unit in plan.main_units else 0.55
            if actual < max(1, int(desired * threshold)):
                deficits.append((actual / max(1.0, desired), unit))
        deficits.sort(key=lambda x: x[0])

        primitives = []
        for _, unit in deficits:
            p = UNIT_TO_PRIMITIVE.get(unit)
            if p:
                primitives.append(p)
        # If ratios are okay, continue reinforcing main units first.
        for unit in plan.main_units:
            p = UNIT_TO_PRIMITIVE.get(unit)
            if p:
                primitives.append(p)
        for unit in plan.support_units:
            if unit in plan.support_caps and counts.get(unit, 0) >= plan.support_caps[unit]:
                continue
            p = UNIT_TO_PRIMITIVE.get(unit)
            if p:
                primitives.append(p)

        # Deduplicate while preserving order.
        seen = set()
        ordered = []
        for p in primitives:
            if p not in seen:
                ordered.append(p)
                seen.add(p)

        res = await self._try_actions(macro_name, ordered)
        if res.ok:
            res.reason = f"produce for plan={plan.name}, main={list(plan.main_units)}; {res.reason}"
            return res
        return MacroExecution(False, macro_name, "", f"plan production failed for {plan.name}: {res.reason}", consumed_turn=False)

    # -----------------------------------------------------------------------------------------
    # Primitive helpers
    # -----------------------------------------------------------------------------------------

    async def _try_actions(self, macro_name: str, primitives: Iterable[str]) -> MacroExecution:
        executor = getattr(self.bot, "executor", None)
        if executor is None:
            return MacroExecution(False, macro_name, "", "no baseline executor", consumed_turn=False)
        fail_reasons = []
        for primitive in primitives:
            try:
                res: ActionResult = await executor.execute(primitive)
            except Exception as exc:
                fail_reasons.append(f"{primitive}: exception {type(exc).__name__}: {exc}")
                continue
            if res is not None and res.ok:
                try:
                    self.bot._record_success(primitive)
                except Exception:
                    pass
                return MacroExecution(True, macro_name, primitive, res.reason, consumed_turn=True)
            fail_reasons.append(f"{primitive}: {getattr(res, 'reason', 'failed')}")
        return MacroExecution(False, macro_name, "", " ; ".join(fail_reasons[:8]), consumed_turn=False)

    def _set_scout_intent(self, intent: str) -> None:
        try:
            self.bot.rl_scout_intent = intent
            self.bot.rl_scout_intent_time = float(getattr(self.bot, "time", 0.0))
        except Exception:
            pass

    async def _attack_intent(self, macro_name: str, min_army_units: int, reason: str) -> MacroExecution:
        executor = getattr(self.bot, "executor", None)
        if executor is None:
            return MacroExecution(False, macro_name, "ATTACK_MOVE", "no executor", consumed_turn=False)
        try:
            res = await executor.attack_move(action=f"RL_{macro_name}_ATTACK", min_army_units=min_army_units, reason=reason)
        except Exception as exc:
            return MacroExecution(False, macro_name, "ATTACK_MOVE", f"exception {type(exc).__name__}: {exc}", consumed_turn=False)
        if res.ok:
            try:
                self.bot._record_success("ATTACK_MOVE")
            except Exception:
                pass
            return MacroExecution(True, macro_name, "ATTACK_MOVE", res.reason, consumed_turn=True)
        return MacroExecution(False, macro_name, "ATTACK_MOVE", res.reason, consumed_turn=False)

    async def _defend_intent(self, macro_name: str) -> MacroExecution:
        executor = getattr(self.bot, "executor", None)
        if executor is None:
            return MacroExecution(False, macro_name, "DEFEND_BASE", "no executor", consumed_turn=False)
        try:
            res = await executor.defend_nearest_base(action=f"RL_{macro_name}_DEFEND")
        except Exception as exc:
            return MacroExecution(False, macro_name, "DEFEND_BASE", f"exception {type(exc).__name__}: {exc}", consumed_turn=False)
        if res.ok:
            try:
                self.bot._record_success("DEFEND_BASE")
            except Exception:
                pass
            return MacroExecution(True, macro_name, "DEFEND_BASE", res.reason, consumed_turn=True)
        return MacroExecution(False, macro_name, "DEFEND_BASE", res.reason, consumed_turn=False)

    @staticmethod
    def _desired_gas_count(o: Dict[str, float], plan: ArmyPlan) -> int:
        t = float(o.get("game_time", 0.0) or 0.0)
        base_target = int(plan.gas_target)
        bases = int(o.get("base_count", 0.0) or 0.0)
        minerals = float(o.get("minerals", 0.0) or 0.0)
        gas = float(o.get("vespene", 0.0) or 0.0)
        # Do not over-gas before the economy can support it, even if a late plan is selected.
        if t < 210:
            target = min(base_target, 2)
        elif t < 330:
            target = min(base_target, 4)
        elif t < 500 and not plan.requires_hive:
            target = min(base_target, 6)
        else:
            target = max(2, min(base_target, 8))
        # Late mineral/gas emergency overrides the conservative plan cap.  Otherwise a
        # midgame plan can trap the bot on too few extractors forever.
        if t >= 300 and minerals >= 1200 and gas <= 250:
            target = max(target, min(6, bases * 2))
        if t >= 420 and minerals >= 1800 and gas <= 420:
            target = max(target, min(8, bases * 2))
        if t >= 540 and minerals >= 2500 and gas <= 700:
            target = max(target, min(10, bases * 2))
        return max(0, int(min(target, max(0, bases * 2))))


def make_action_mask(obs_dict: Dict[str, float], profile: str = "balanced") -> List[float]:
    """Competition-thinking action mask.

    This is intentionally a light curriculum, not a hard script.  It only removes
    actions that are clearly absurd in the current strategic stage.  The rewarder
    supplies the softer learning signal.
    """
    from rl_v1.strategic_stage import infer_stage, is_clearly_bad_action

    mask = [1.0] * ACTION_DIM
    t = obs_dict.get("game_time", 0.0)
    army = obs_dict.get("army_supply", 0.0)
    supply = obs_dict.get("supply_used", 0.0)
    workers = obs_dict.get("worker_count", 0.0)
    worker_deficit = obs_dict.get("worker_deficit", 0.0)
    threats = obs_dict.get("visible_threats_near_home", 0.0)
    has_lair = obs_dict.get("has_lair", 0.0) > 0.5
    profile = str(profile or "balanced").strip().lower()
    stage = infer_stage(obs_dict)
    gas_emergency = bool(
        (t >= 300 and obs_dict.get("minerals", 0.0) >= 1200 and obs_dict.get("vespene", 0.0) <= 250)
        or (t >= 420 and obs_dict.get("minerals", 0.0) >= 1800 and obs_dict.get("vespene", 0.0) <= 420)
        or (t >= 540 and obs_dict.get("minerals", 0.0) >= 2500 and obs_dict.get("vespene", 0.0) <= 700)
    )
    if gas_emergency and obs_dict.get("supply_used", 0.0) < 195 and obs_dict.get("visible_threats_worker_line", 0.0) < 1:
        # Keep exploration, but prevent the worst loop: choosing pressure/scout/noop while
        # sitting on thousands of minerals and no gas.
        for a in [MacroAction.DO_NOTHING, MacroAction.LING_PRESSURE, MacroAction.ROACH_PRESSURE, MacroAction.SCOUT_FOCUS]:
            mask[a] = 0.0
        mask[MacroAction.ECON_MACRO] = 1.0
        mask[MacroAction.FAST_LAIR_TECH] = 1.0
        mask[MacroAction.FAST_HIVE_TECH] = 1.0

    # Universal sanity gates.
    if stage in {"defense", "plan_setup", "late_transition", "timing_attack", "map_hunt"}:
        mask[MacroAction.DO_NOTHING] = 0.0
    if obs_dict.get("plan_stuck", 0.0) > 0.5 or obs_dict.get("plan_unrealized", 0.0) > 0.5:
        mask[MacroAction.DO_NOTHING] = 0.0
        if obs_dict.get("plan_tech_missing_count", 0.0) > 0.5:
            mask[MacroAction.MAXED_ATTACK] = 0.0
            mask[MacroAction.LING_PRESSURE] = 0.0

    if army < 20 and supply < 150:
        mask[MacroAction.MAXED_ATTACK] = 0.0
    if t > 420 or has_lair or workers >= 45:
        mask[MacroAction.LING_PRESSURE] = 0.0
    if t < 330 and not has_lair:
        mask[MacroAction.FAST_HIVE_TECH] = 0.0

    # v2.5 anti-all-in mask: under real early pressure, keep exploration inside
    # defensive/economy-survival choices instead of letting SCOUT/TECH/DO_NOTHING
    # burn the few critical decisions before death.
    if obs_dict.get("early_allin_danger", 0.0) > 0.5:
        for a in [
            MacroAction.SCOUT_FOCUS, MacroAction.FAST_LAIR_TECH, MacroAction.FAST_HIVE_TECH,
            MacroAction.UPGRADE_FOCUS, MacroAction.DO_NOTHING, MacroAction.MAXED_ATTACK, MacroAction.LING_PRESSURE,
        ]:
            mask[a] = 0.0
        if threats >= 6 or obs_dict.get("visible_threats_worker_line", 0.0) >= 1:
            mask[MacroAction.ECON_MACRO] = 0.0
        mask[MacroAction.DEFENSIVE_HOLD] = 1.0
        mask[MacroAction.ROACH_PRESSURE] = 1.0

    # During worker recovery and third/fourth debt, do not let pressure actions steal the economy.
    if worker_deficit >= 12 and supply < 185 and threats < 8:
        for a in [MacroAction.LING_PRESSURE, MacroAction.ROACH_PRESSURE, MacroAction.MAXED_ATTACK]:
            mask[a] = 0.0
    if t < 280 and obs_dict.get("expand_debt", 0.0) > 0.5 and obs_dict.get("minerals", 0.0) < 360:
        mask[MacroAction.UPGRADE_FOCUS] = 0.0
        mask[MacroAction.FAST_HIVE_TECH] = 0.0
        mask[MacroAction.MAXED_ATTACK] = 0.0

    if profile in {"economy", "macro_economy", "macro-only", "macro_only", "competition", "match", "ladder"}:
        # Economy profile is no longer pure self-build forever.  It now allows timing
        # and late-transition lessons once the economy is established.
        if stage in {"economy_buildout", "worker_recovery"}:
            for a in [MacroAction.LING_PRESSURE, MacroAction.ROACH_PRESSURE, MacroAction.MAXED_ATTACK]:
                mask[a] = 0.0
            if obs_dict.get("expand_debt", 0.0) > 0.5 and obs_dict.get("minerals", 0.0) < 360:
                mask[MacroAction.ROACH_HYDRA_TIMING] = 0.0
        if stage == "defense":
            mask[MacroAction.DO_NOTHING] = 0.0
            # Keep economy legal for minor threats, but block greed under real pressure.
            if threats >= 6 or obs_dict.get("visible_threats_worker_line", 0.0) >= 1:
                for a in [MacroAction.SCOUT_FOCUS, MacroAction.FAST_LAIR_TECH, MacroAction.FAST_HIVE_TECH, MacroAction.UPGRADE_FOCUS, MacroAction.MAXED_ATTACK, MacroAction.LING_PRESSURE]:
                    mask[a] = 0.0
            if threats >= 10:
                for a in [MacroAction.LING_PRESSURE, MacroAction.ROACH_PRESSURE, MacroAction.MAXED_ATTACK]:
                    mask[a] = 0.0
        if stage == "late_transition":
            mask[MacroAction.DO_NOTHING] = 0.0
            for a in [MacroAction.LING_PRESSURE, MacroAction.ROACH_PRESSURE]:
                mask[a] = 0.0
        if stage in {"timing_attack", "map_hunt"}:
            if supply >= 195 and obs_dict.get("expand_debt", 0.0) < 0.5:
                mask[MacroAction.ECON_MACRO] = 0.0
                mask[MacroAction.DO_NOTHING] = 0.0
            mask[MacroAction.LING_PRESSURE] = 0.0
        if obs_dict.get("worker_excess", 0.0) >= 6 and supply >= 170:
            # Teach it to stop droning when already over the plan cap.
            if obs_dict.get("expand_debt", 0.0) < 0.5:
                mask[MacroAction.ECON_MACRO] = 0.0

    if obs_dict.get("supply_used", 0.0) >= 190 and obs_dict.get("expand_debt", 0.0) < 0.5:
        mask[MacroAction.DO_NOTHING] = 0.0
        mask[MacroAction.ECON_MACRO] = 0.0
    if obs_dict.get("spend_bank_urgency", 0.0) >= 1.0:
        mask[MacroAction.DO_NOTHING] = 0.0
        mask[MacroAction.SCOUT_FOCUS] = 0.0

    # v2.9: once a real attack window exists, stop sampling scout/no-op/greed.
    # The executor still contains defense overrides; this only prevents the policy
    # from idling with a ready army.
    if obs_dict.get("timing_attack_due", 0.0) > 0.5 and army >= 50:
        for a in [MacroAction.DO_NOTHING, MacroAction.SCOUT_FOCUS, MacroAction.ECON_MACRO, MacroAction.UPGRADE_FOCUS]:
            mask[a] = 0.0
        mask[MacroAction.ROACH_HYDRA_TIMING] = 1.0
        mask[MacroAction.MAXED_ATTACK] = 1.0

    if t >= 360 and (obs_dict.get("plan_stuck", 0.0) > 0.5 or obs_dict.get("plan_unrealized", 0.0) > 0.5):
        mask[MacroAction.SCOUT_FOCUS] = 0.0
        mask[MacroAction.DO_NOTHING] = 0.0

    # Final pass: remove only strategically absurd actions.
    for a in MacroAction:
        if is_clearly_bad_action(stage, a.name, obs_dict):
            mask[a] = 0.0

    # Never allow an all-zero mask.
    if not any(v > 0 for v in mask):
        mask[MacroAction.ECON_MACRO] = 1.0
        mask[MacroAction.DEFENSIVE_HOLD] = 1.0
    return mask
