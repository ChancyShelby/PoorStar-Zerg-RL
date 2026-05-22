# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Optional

from poorstar.bot import PoorStarBot

from rl_v1.agent import MacroAgent
from rl_v1.rl_controller import RLController
from rl_v1.state_features import FEATURE_DIM
from rl_v1.resign_detector import ResignDetector
from rl_v1.advanced_unit_control import AdvancedUnitControl
from rl_v1.economy_support import EconomySupportManager
from rl_v1.map_hunt_manager import MapHuntManager
from rl_v1.hard_scaffold_manager import HardScaffoldManager
from rl_v1.combat_coordinator import CombatCoordinator
from rl_v1.tactical_targeting import TacticalTargetingManager


class RLPoorStarBot(PoorStarBot):
    """
    PoorStar v1.23 + Macro-RL v1.

    v0.2 no-log 改动：
    - 默认不写 PoorStar 每步 jsonl。
    - 默认不写 RL 每步 jsonl。
    - episode 结束只保留 summary。
    - 控制台可通过 train/play 的 --verbose 打开；默认静默跑，减少卡顿。
    """

    def __init__(
        self,
        model_dir: Path,
        agent: MacroAgent,
        opening_time: float = 150.0,
        decision_interval: float = 1.0,
        topk: int = 5,
        enable_safety: bool = True,
        enable_rule_after_opening: bool = True,
        log_dir: Path | str = "runs",
        rl_start_time: float = 150.0,
        rl_decision_interval: float = 10.0,
        train_rl: bool = True,
        greedy_rl: bool = False,
        quiet: bool = True,
        write_poorstar_log: bool = False,
        write_rl_step_log: bool = False,
        write_summary: bool = True,
        enable_resign: bool = True,
        enable_advanced_unit_control: bool = True,
        enable_economy_support: bool = True,
        training_profile: str = "economy",
        resign_min_time: float = 420.0,
        resign_persist_seconds: float = 18.0,
    ):
        super().__init__(
            model_dir=model_dir,
            opening_time=opening_time,
            decision_interval=decision_interval,
            topk=topk,
            enable_safety=enable_safety,
            enable_rule_after_opening=enable_rule_after_opening,
            log_dir=Path(log_dir) / "poorstar_logs",
        )
        self.agent = agent
        raw_rl_start_time = float(rl_start_time)
        profile_key = str(training_profile or "economy").strip().lower()
        # v2.9: 150s 接管太早，会把开局/三矿/二本/防守全部冲烂。
        # competition / ladder profile 下强制 baseline 至少控到 7:00 左右。
        min_safe_rl_start = 420.0 if profile_key in {"competition", "match", "ladder"} else 300.0
        self.rl_start_time = max(raw_rl_start_time, min_safe_rl_start)
        self.rl_decision_interval = float(rl_decision_interval)
        self.train_rl = bool(train_rl)
        self.greedy_rl = bool(greedy_rl)
        self.quiet = bool(quiet)
        self.write_poorstar_log = bool(write_poorstar_log)
        self.write_rl_step_log = bool(write_rl_step_log)
        self.write_summary = bool(write_summary)
        self.rl_log_dir = Path(log_dir) / "rl_logs"
        self.rl_controller: Optional[RLController] = None
        self.rl_scout_intent = ""
        self.rl_scout_intent_time = -999.0
        self.last_episode_summary: Optional[dict] = None
        self.enemy_gg_seen = False
        self.enemy_gg_time = -999.0
        self.rl_current_intent = ""
        self.rl_current_intent_time = -999.0
        self.enable_resign = bool(enable_resign)
        self.enable_advanced_unit_control = bool(enable_advanced_unit_control)
        self.enable_economy_support = bool(enable_economy_support)
        self.training_profile = str(training_profile or "economy")
        self.resign_min_time = float(resign_min_time)
        self.resign_persist_seconds = float(resign_persist_seconds)
        self.resign_detector = None
        self.advanced_unit_control = None
        self.economy_support = None
        self.map_hunt_manager = None
        self.hard_scaffold_manager = None
        self.combat_coordinator = None
        self.tactical_targeting = None
        self.rl_army_plan = "early_basic_roach_ling_bane"
        self.rl_army_plan_reason = "initial"
        self._resign_triggered = False
        self._resign_reason = ""
        # v2.8 performance throttle.  Late game stalls are usually caused by expensive
        # manager scans / get_available_abilities calls every bot step.  We keep combat
        # responsive, but run scout/creep/advanced/econ support at controlled intervals.
        self._last_scout_manager_time = -999.0
        self._last_queen_manager_time = -999.0
        self._last_creep_manager_time = -999.0
        self._last_adv_manager_time = -999.0
        self._last_econ_support_time = -999.0
        # v2.9: RL is allowed to tune strategy, but it must not steal the whole
        # macro skeleton.  This guard lets the deterministic baseline repair
        # must-not-break loops first: supply, gas saturation, tech debt, huge bank,
        # worker recovery and attack timing.
        self._last_hard_rule_guard_time = -999.0

    def _say(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    async def on_start(self):
        await super().on_start()
        if not self.write_poorstar_log:
            # PoorStarBot.on_start 会打开 jsonl；训练时关闭，避免每步磁盘 I/O。
            try:
                if self.log_f:
                    self.log_f.close()
            except Exception:
                pass
            self.log_f = None
            self.log_path = None

        self.rl_controller = RLController(
            bot=self,
            agent=self.agent,
            log_dir=self.rl_log_dir,
            rl_start_time=self.rl_start_time,
            rl_decision_interval=self.rl_decision_interval,
            train=self.train_rl,
            greedy=self.greedy_rl,
            write_step_log=self.write_rl_step_log,
            write_summary=self.write_summary,
            training_profile=self.training_profile,
        )
        self.resign_detector = ResignDetector(self, persist_seconds=self.resign_persist_seconds, min_time=self.resign_min_time) if self.enable_resign else None
        self.advanced_unit_control = AdvancedUnitControl(self, interval=1.0, max_units_per_step=18) if self.enable_advanced_unit_control else None
        self.economy_support = EconomySupportManager(self) if self.enable_economy_support else None
        self.map_hunt_manager = MapHuntManager(self)
        self.hard_scaffold_manager = HardScaffoldManager(self)
        self.combat_coordinator = CombatCoordinator(self)
        self.tactical_targeting = TacticalTargetingManager(self, interval=3.0)
        self._say("=" * 100)
        self._say("MACRO-RL V1 ATTACHED")
        self._say(f"obs_dim              : {FEATURE_DIM}")
        self._say(f"rl_start_time        : {self.rl_start_time}")
        self._say(f"rl_decision_interval : {self.rl_decision_interval}")
        self._say(f"train_rl             : {self.train_rl}")
        self._say(f"greedy_rl            : {self.greedy_rl}")
        self._say(f"write_poorstar_log   : {self.write_poorstar_log}")
        self._say(f"write_rl_step_log    : {self.write_rl_step_log}")
        self._say(f"training_profile     : {self.training_profile}")
        self._say(f"enable_resign        : {self.enable_resign}")
        self._say(f"resign_min_time      : {self.resign_min_time}")
        self._say(f"resign_persist_secs  : {self.resign_persist_seconds}")
        self._say(f"enable_adv_control   : {self.enable_advanced_unit_control}")
        self._say(f"enable_econ_support  : {self.enable_economy_support}")
        self._say("enable_map_hunt      : True")
        self._say("enable_combat_coord  : True")
        self._say(f"summary_dir          : {self.rl_log_dir}")
        self._say("=" * 100)

    def log_event(self, obj: dict):
        if self.write_poorstar_log:
            return super().log_event(obj)
        return None


    async def on_chat(self, message: str, player_id: int = None):
        """
        Some Computer AIs type GG but python-sc2 may close the websocket before Result.Victory
        is propagated. Track enemy GG so the RL controller can mark the episode as victory.
        """
        try:
            await super().on_chat(message, player_id)
        except TypeError:
            try:
                await super().on_chat(message)
            except Exception:
                pass
        except Exception:
            pass

        msg = str(message or "").strip().lower()
        if player_id is not None and int(player_id) == int(getattr(self, "player_id", -1)):
            return
        if msg in {"gg", "ggwp", "wp"} or " gg" in f" {msg} " or "ggwp" in msg:
            self.enemy_gg_seen = True
            self.enemy_gg_time = float(getattr(self, "time", 0.0))
            self._say(f"[RL] enemy GG detected at {self.enemy_gg_time:.1f}s: {message!r}")

    def force_finish_episode(self, result_hint: str = "UnknownConnectionClosed") -> Optional[dict]:
        """
        Called from train/play exception handlers when SC2 closes the websocket before on_end.
        This prevents a real GG/victory from being silently dropped.
        """
        if self.last_episode_summary is not None:
            return self.last_episode_summary
        if self.rl_controller is None:
            return None
        try:
            summary = self.rl_controller.finish_episode(result_hint)
            self.last_episode_summary = summary
            return summary
        except Exception as exc:
            self._say(f"[RL] force_finish_episode failed: {type(exc).__name__}: {exc}")
            return None

    async def _leave_game_safely(self) -> None:
        # python-sc2 / burnysc2 versions differ slightly; try common paths.
        try:
            await self.chat_send("gg")
        except Exception:
            pass
        for obj_name in ["client", "_client"]:
            try:
                client = getattr(self, obj_name, None)
                leave = getattr(client, "leave", None)
                if leave is not None:
                    await leave()
                    return
            except Exception:
                continue

    async def _maybe_resign(self) -> bool:
        if not self.enable_resign or self._resign_triggered or self.resign_detector is None:
            return False
        decision = self.resign_detector.check()
        if not decision.should_resign:
            return False
        self._resign_triggered = True
        self._resign_reason = str(decision.reason)
        self._say(f"[RL] resign triggered: {self._resign_reason}")
        if self.rl_controller is not None and self.last_episode_summary is None:
            try:
                summary = self.rl_controller.finish_episode(f"ResignedDefeat({self._resign_reason})")
                self.last_episode_summary = summary
            except Exception as exc:
                self._say(f"[RL] finish on resign failed: {type(exc).__name__}: {exc}")
        await self._leave_game_safely()
        return True

    async def on_end(self, result):
        if self.rl_controller is not None and self.last_episode_summary is None:
            try:
                summary = self.rl_controller.finish_episode(result)
                self.last_episode_summary = summary
                self._say("=" * 100)
                self._say("RL EPISODE FINISHED")
                self._say(str(summary))
                self._say("=" * 100)
            except Exception as exc:
                self._say(f"[RL] finish_episode failed: {type(exc).__name__}: {exc}")
        await super().on_end(result)

    def _refresh_army_plan(self) -> None:
        """Keep rl_army_plan fresh even before RL starts.

        RuleMacroManager and ResourceBalanceManager read bot.rl_army_plan.  In the old
        wrapper that field was only updated inside MacroActionExecutor, so delaying RL
        to protect the opening also accidentally delayed tech-plan selection.  This
        helper updates the selector without consuming an RL action.
        """
        try:
            controller = getattr(self, "rl_controller", None)
            executor = getattr(controller, "macro_executor", None)
            if executor is not None:
                executor._current_plan()
        except Exception:
            pass

    def _hard_rule_guard_due(self) -> tuple[bool, str]:
        """Return whether the rule baseline must run before RL this frame.

        This is the key v2.9 fix.  RL should not decide whether we are allowed to
        fill gas, make overlords, spend a 2k mineral bank, repair a missing tech
        chain, or launch a maxed army.  Those are hard invariants.
        """
        try:
            from rl_v1.state_features import extract_observation
            obs = extract_observation(self)
        except Exception as exc:
            return False, f"obs failed: {type(exc).__name__}: {exc}"

        t = float(obs.get("game_time", 0.0) or 0.0)
        if t <= float(self.opening_time):
            return False, "still opening"

        if t - float(getattr(self, "_last_hard_rule_guard_time", -999.0)) < 2.0:
            return False, "cooldown"

        supply_used = float(obs.get("supply_used", 0.0) or 0.0)
        supply_left = float(obs.get("supply_left", 0.0) or 0.0)
        army = float(obs.get("army_supply", 0.0) or 0.0)
        minerals = float(obs.get("minerals", 0.0) or 0.0)
        gas = float(obs.get("vespene", 0.0) or 0.0)
        gas_debt = float(obs.get("gas_worker_debt", 0.0) or 0.0)
        expand_debt = float(obs.get("expand_debt", 0.0) or 0.0)
        worker_deficit = float(obs.get("worker_deficit", 0.0) or 0.0)

        if supply_left <= 2 and supply_used < 196:
            return True, f"hard supply guard: left={supply_left:.0f}, used={supply_used:.0f}"
        if obs.get("gas_economy_emergency", 0.0) > 0.5 or gas_debt >= 6:
            return True, f"hard gas guard: gas_debt={gas_debt:.0f}, minerals={minerals:.0f}, gas={gas:.0f}"
        if expand_debt > 0.5 and minerals >= 300 and supply_used < 180:
            return True, f"hard expand guard: expand_debt={expand_debt}, minerals={minerals:.0f}"
        if worker_deficit >= 10 and supply_used < 170:
            return True, f"hard worker recovery guard: deficit={worker_deficit:.0f}"
        if obs.get("plan_stuck", 0.0) > 0.5 or obs.get("plan_unrealized", 0.0) > 0.5:
            return True, "hard plan guard: selected tech/unit plan unrealized"
        if obs.get("late_transition_due", 0.0) > 0.5:
            return True, "hard late transition guard"
        if obs.get("spend_bank_urgency", 0.0) >= 0.7:
            return True, f"hard spend-bank guard: urgency={obs.get('spend_bank_urgency', 0.0):.2f}, bank={minerals:.0f}/{gas:.0f}"
        if obs.get("timing_attack_due", 0.0) > 0.5 and army >= 55:
            return True, f"hard timing/attack guard: army={army:.0f}, supply={supply_used:.0f}"
        if supply_used >= 185 and army >= 80:
            return True, f"hard near-max attack guard: army={army:.0f}, supply={supply_used:.0f}"

        return False, "no hard rule needed"

    async def _run_hard_rule_guard(self, iteration: int) -> bool:
        if not self.enable_rule_after_opening or self.rule_macro is None:
            return False
        due, reason = self._hard_rule_guard_due()
        if not due:
            return False
        self._last_hard_rule_guard_time = float(getattr(self, "time", 0.0))
        try:
            res = await self.rule_macro.step()
        except Exception as exc:
            self._say(f"[RL] hard rule guard failed: {type(exc).__name__}: {exc}")
            return False
        if res is not None and res.ok:
            self._record_success(res.action)
            self._say(f"[{self.time:06.1f}] HARD_RULE {res.action} | {reason} | {res.reason}")
            self.log_event({
                "time_sec": float(self.time),
                "iteration": int(iteration),
                "phase": "hard_rule_guard",
                "executed": True,
                "executed_action": res.action,
                "guard_reason": reason,
                "reason": res.reason,
            })
            return True
        return False

    async def on_step(self, iteration: int):
        if self.time - self.last_decision_time < self.decision_interval:
            return
        self.last_decision_time = float(self.time)

        if self.combat_coordinator is not None:
            try:
                self.combat_coordinator.begin_step(iteration)
            except Exception as exc:
                self._say(f"[RL] combat_coordinator begin failed: {type(exc).__name__}: {exc}")

        assert self.executor is not None
        assert self.safety is not None
        assert self.rule_macro is not None
        assert self.combat is not None
        assert self.scout is not None
        assert self.creep is not None
        assert self.queen_manager is not None
        assert self.resource_balance is not None
        assert self.policy is not None
        assert self.gate is not None

        if await self._maybe_resign():
            return

        # Expensive background managers are throttled independently.  This is important
        # after 10+ minutes when there are many units, tumors and scout units.
        now = float(self.time)
        scout_interval = 3.0 if now < 420 else 5.0
        queen_interval = 1.0
        creep_interval = 5.0 if now < 540 else 8.0

        if now - self._last_scout_manager_time >= scout_interval:
            self._last_scout_manager_time = now
            await self.scout.step(iteration)
        if now - self._last_queen_manager_time >= queen_interval:
            self._last_queen_manager_time = now
            await self.queen_manager.step(iteration)
        if now - self._last_creep_manager_time >= creep_interval:
            self._last_creep_manager_time = now
            await self.creep.step(iteration)

        # Update selected army plan before any gas/rule logic reads it.
        self._refresh_army_plan()

        # v3.0: absolute hard scaffold. This runs before RL and before optional macro.
        # It directly fixes the screenshot-class failure: 10k+ minerals, ~0 gas,
        # no new bases, scattered/idle army. It does not wait for the policy to learn.
        if self.hard_scaffold_manager is not None:
            try:
                hard_res = await self.hard_scaffold_manager.step(iteration)
                if hard_res is not None:
                    self.log_event({
                        "time_sec": float(self.time),
                        "iteration": int(iteration),
                        "phase": "hard_scaffold",
                        "executed": True,
                        "built_gas": int(getattr(hard_res, "built_gas", 0)),
                        "assigned_gas": int(getattr(hard_res, "assigned_gas", 0)),
                        "pulled_off_gas": int(getattr(hard_res, "pulled_off_gas", 0)),
                        "expanded": bool(getattr(hard_res, "expanded", False)),
                        "rallied": int(getattr(hard_res, "rallied", 0)),
                        "attacked": int(getattr(hard_res, "attacked", 0)),
                        "spent_larva": int(getattr(hard_res, "spent_larva", 0)),
                        "made_units": str(getattr(hard_res, "made_units", "")),
                        "reason": str(getattr(hard_res, "reason", "")),
                    })
                    self._say(
                        f"[{self.time:06.1f}] HARD_SCAFFOLD "
                        f"gas+{int(getattr(hard_res, 'built_gas', 0))}/workers+{int(getattr(hard_res, 'assigned_gas', 0))}/off-{int(getattr(hard_res, 'pulled_off_gas', 0))} "
                        f"expand={bool(getattr(hard_res, 'expanded', False))} "
                        f"rally={int(getattr(hard_res, 'rallied', 0))} attack={int(getattr(hard_res, 'attacked', 0))} "
                        f"spend={int(getattr(hard_res, 'spent_larva', 0))} units={str(getattr(hard_res, 'made_units', ''))} | "
                        f"{str(getattr(hard_res, 'reason', ''))}"
                    )
                    if (getattr(hard_res, "attacked", 0) or 0) > 0:
                        return
            except Exception as exc:
                self._say(f"[RL] hard_scaffold failed: {type(exc).__name__}: {exc}")

        if self.economy_support is not None and now - self._last_econ_support_time >= 2.5:
            self._last_econ_support_time = now
            try:
                econ_support_res = await self.economy_support.step()
                if econ_support_res is not None and (econ_support_res.moved > 0 or getattr(econ_support_res, "built_gas", False) or getattr(econ_support_res, "assigned_gas", False)):
                    self.log_event({
                        "time_sec": float(self.time),
                        "iteration": int(iteration),
                        "phase": "economy_support",
                        "executed": True,
                        "executed_action": "WORKER_TRANSFER",
                        "reason": econ_support_res.reason,
                    })
            except Exception as exc:
                self._say(f"[RL] economy_support failed: {type(exc).__name__}: {exc}")

        if self.advanced_unit_control is not None and now - self._last_adv_manager_time >= (1.1 if now < 900 else 1.6):
            self._last_adv_manager_time = now
            try:
                adv_res = await self.advanced_unit_control.step(iteration)
                if adv_res is not None and adv_res.actions > 0:
                    self.log_event({
                        "time_sec": float(self.time),
                        "iteration": int(iteration),
                        "phase": "advanced_unit_control",
                        "executed": True,
                        "executed_action": "ADVANCED_UNIT_CONTROL",
                        "reason": adv_res.reason,
                    })
            except Exception as exc:
                self._say(f"[RL] advanced_unit_control failed: {type(exc).__name__}: {exc}")

        econ_res = await self.resource_balance.step()
        if econ_res is not None and econ_res.ok:
            self._say(f"[{self.time:06.1f}] ECON {econ_res.action} | {econ_res.reason}")
            self.log_event({
                "time_sec": float(self.time),
                "iteration": int(iteration),
                "phase": "resource_balance",
                "executed": True,
                "executed_action": econ_res.action,
                "reason": econ_res.reason,
            })

        # v3.5: tactical layer.  This runs before the generic CombatManager so a stuck
        # frontal push can rotate to an exposed expansion, and high-ground pushes can
        # request an air unit for vision.  If it issued a real army attack, consume this
        # decision tick; if it only moved a scout for vision, let normal combat continue.
        if self.tactical_targeting is not None:
            try:
                tac_res = await self.tactical_targeting.step(iteration)
                if tac_res is not None and tac_res.ok:
                    self.log_event({
                        "time_sec": float(self.time),
                        "iteration": int(iteration),
                        "phase": "tactical_targeting",
                        "executed": True,
                        "issued_attack": int(getattr(tac_res, "issued_attack", 0)),
                        "issued_vision": int(getattr(tac_res, "issued_vision", 0)),
                        "target": str(getattr(tac_res, "target", "")),
                        "mode": str(getattr(tac_res, "mode", "")),
                        "reason": str(getattr(tac_res, "reason", "")),
                    })
                    if int(getattr(tac_res, "issued_attack", 0)) > 0:
                        self._say(
                            f"[{self.time:06.1f}] TACTICAL {getattr(tac_res, 'mode', '')} "
                            f"attack={getattr(tac_res, 'issued_attack', 0)} vision={getattr(tac_res, 'issued_vision', 0)} | "
                            f"{getattr(tac_res, 'reason', '')}"
                        )
                        return
            except Exception as exc:
                self._say(f"[RL] tactical_targeting failed: {type(exc).__name__}: {exc}")

        res = await self.combat.step()
        if res is not None and res.ok:
            self._record_success(res.action)
            self._say(f"[{self.time:06.1f}] COMBAT {res.action} | {res.reason}")
            self.log_event({
                "time_sec": float(self.time),
                "iteration": int(iteration),
                "phase": "combat",
                "executed": True,
                "executed_action": res.action,
                "reason": res.reason,
            })
            return

        # v2.3: after enemy main/natural are destroyed, do not idle at the dead main.
        # If no enemy structure is visible, periodically sweep expansion locations.
        if self.map_hunt_manager is not None and self.time > self.opening_time:
            try:
                hunt_res = await self.map_hunt_manager.step(iteration)
                if hunt_res is not None and hunt_res.ok:
                    self._say(f"[{self.time:06.1f}] HUNT {hunt_res.target} | {hunt_res.reason}")
                    self.log_event({
                        "time_sec": float(self.time),
                        "iteration": int(iteration),
                        "phase": "map_hunt",
                        "executed": True,
                        "executed_action": "HUNT_REMAINING_BASES",
                        "target": str(hunt_res.target),
                        "reason": hunt_res.reason,
                    })
                    return
            except Exception as exc:
                self._say(f"[RL] map_hunt failed: {type(exc).__name__}: {exc}")

        if self.time <= self.opening_time:
            did_opening_action = await self.opening_model_step(iteration)
            if did_opening_action:
                return

            if self.enable_safety:
                res = await self.safety.step()
                if res is not None and res.ok:
                    self._record_success(res.action)
                    self._say(f"[{self.time:06.1f}] SAFETY {res.action} | {res.reason}")
                    self.log_event({
                        "time_sec": float(self.time),
                        "iteration": int(iteration),
                        "phase": "safety",
                        "executed": True,
                        "executed_action": res.action,
                        "reason": res.reason,
                    })
                    return
            return

        if self.enable_safety:
            res = await self.safety.step(allow_inject_return=False)
            if res is not None and res.ok:
                self._record_success(res.action)
                self._say(f"[{self.time:06.1f}] SAFETY {res.action} | {res.reason}")
                self.log_event({
                    "time_sec": float(self.time),
                    "iteration": int(iteration),
                    "phase": "safety_critical",
                    "executed": True,
                    "executed_action": res.action,
                    "reason": res.reason,
                })
                return

        # v2.9: before RL can consume the turn, let the deterministic skeleton fix
        # non-negotiable macro failures.  This is why the bot should stop floating
        # huge mineral banks, sitting on empty gas, or refusing to transition.
        if await self._run_hard_rule_guard(iteration):
            return

        if self.rl_controller is not None:
            rl_res = await self.rl_controller.maybe_step(iteration)
            if rl_res is not None and rl_res.ok and rl_res.consumed_turn:
                self._say(f"[{self.time:06.1f}] RL {rl_res.macro_action} -> {rl_res.primitive_action} | {rl_res.reason}")
                self.log_event({
                    "time_sec": float(self.time),
                    "iteration": int(iteration),
                    "phase": "macro_rl",
                    "executed": True,
                    "executed_action": rl_res.macro_action,
                    "primitive_action": rl_res.primitive_action,
                    "reason": rl_res.reason,
                })
                return

        if self.enable_rule_after_opening:
            res = await self.rule_macro.step()
            if res is not None and res.ok:
                self._record_success(res.action)
                self._say(f"[{self.time:06.1f}] RULE {res.action} | {res.reason}")
                self.log_event({
                    "time_sec": float(self.time),
                    "iteration": int(iteration),
                    "phase": "rule_macro",
                    "executed": True,
                    "executed_action": res.action,
                    "reason": res.reason,
                })
                return
