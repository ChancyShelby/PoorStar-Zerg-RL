# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict


class RewardComputer:
    """
    Macro-RL v1 shaping reward。

    核心变化：
    1. 奖励战略意图的一致性，而不是散装动作。
    2. 加入 mineral saturation 的持续惩罚：单矿 16 农左右满采，超出越多、持续越久扣得越多。
    3. GG / inferred victory 识别。
    """

    def __init__(self):
        pass

    def step_reward(
        self,
        prev: Dict[str, float],
        cur: Dict[str, float],
        action_name: str,
        executed_ok: bool,
    ) -> float:
        r = 0.0
        a = str(action_name or "").upper()
        try:
            from rl_v1.strategic_stage import infer_stage, recommended_actions, is_clearly_bad_action
            stage = infer_stage(cur)
            teacher_actions = recommended_actions(stage, cur)
        except Exception:
            stage = "plan_production"
            teacher_actions = set()
            is_clearly_bad_action = None

        # -----------------------------------------------------------------------------------------
        # v2.4 比赛思路 teacher signal：让 RL 逐步学会当前是运营、侦察、成型、进攻、转型还是扫图。
        # 这不是写死脚本，只是 reward shaping；模型仍然要自己通过胜负和过程奖励学习。
        # -----------------------------------------------------------------------------------------

        if a in teacher_actions:
            r += 0.16
            if executed_ok:
                r += 0.05
        elif a == "DO_NOTHING" and stage not in {"plan_production", "scout"}:
            r -= 0.45

        # v2.7: literal idling is now treated as a training error whenever the game
        # asks for defense, setup, transition, attack, or spending a large bank.  The
        # executor may convert it into a fallback action, but the policy still learns
        # that selecting DO_NOTHING was bad.
        if a == "DO_NOTHING":
            if cur.get("supply_used", 0.0) >= 170 or cur.get("bank_too_high", 0.0) > 0.5 or cur.get("spend_bank_urgency", 0.0) >= 0.8:
                r -= 0.75
            if cur.get("plan_stuck", 0.0) > 0.5 or cur.get("plan_unrealized", 0.0) > 0.5:
                r -= 0.85

        if is_clearly_bad_action is not None and is_clearly_bad_action(stage, a, cur):
            r -= 0.45

        # v2.5: explicit anti-all-in curriculum.  A loss at 6:00 with workers=0 is
        # usually not a macro lesson; it means the policy ignored emergency defense.
        # Reward the intent that buys survival and punish greedy scout/tech under pressure.
        if cur.get("early_allin_danger", 0.0) > 0.5:
            if a == "DEFENSIVE_HOLD":
                r += 0.65
                if executed_ok:
                    r += 0.12
            elif a in {"SCOUT_FOCUS", "FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS", "DO_NOTHING", "MAXED_ATTACK"}:
                r -= 0.65
            elif a == "ECON_MACRO" and cur.get("visible_threats_worker_line", 0.0) >= 1:
                r -= 0.55

        # -----------------------------------------------------------------------------------------
        # 经济结构：总农民数、基地数、饱和度必须匹配。
        # -----------------------------------------------------------------------------------------

        worker_delta = cur.get("worker_count", 0.0) - prev.get("worker_count", 0.0)
        if cur.get("worker_count", 0.0) <= 84:
            r += 0.08 * max(-3.0, min(5.0, worker_delta))

        deficit = cur.get("worker_deficit", 0.0)
        if deficit > 0:
            r -= min(1.5, 0.04 * deficit)
        else:
            r += 0.04

        # 过饱和：每 10 秒反复扣，所以天然是 time-integral penalty。
        overflow = cur.get("worker_overflow_total", 0.0)
        max_over = cur.get("max_base_overflow", 0.0)
        if overflow > 0:
            # 17 农小扣；20+ 农明显扣；24+ 农重扣。
            r -= min(1.2, 0.025 * overflow + 0.018 * (max_over ** 2))

        # 欠饱和：有基地但是没人采，也扣。
        underflow = cur.get("worker_underflow_total", 0.0)
        if underflow > 0 and cur.get("base_count", 0.0) >= 3:
            r -= min(0.8, 0.018 * underflow)

        # 饱和度整体误差。
        r -= min(0.4, 0.18 * cur.get("avg_saturation_error", 0.0))

        # v2.4: worker cap is plan/stage-aware.  87/70 这种局面要被稳定扣分。
        worker_excess = float(cur.get("worker_excess", 0.0) or 0.0)
        if worker_excess > 0:
            r -= min(1.0, 0.045 * worker_excess + 0.008 * (worker_excess ** 2))
            if a == "ECON_MACRO" and worker_delta > 0:
                r -= min(0.65, 0.06 * worker_excess)

        idle = cur.get("idle_worker_count", 0.0)
        if idle > 0:
            r -= min(0.4, 0.025 * idle)

        # 扩张完成/开矿。
        base_delta = (cur.get("base_count", 0.0) + cur.get("pending_base_count", 0.0)) - (
            prev.get("base_count", 0.0) + prev.get("pending_base_count", 0.0)
        )
        r += 1.1 * max(0.0, base_delta)

        # -----------------------------------------------------------------------------------------
        # 科技和升级。
        # -----------------------------------------------------------------------------------------

        if prev.get("has_lair", 0.0) < 0.5 and cur.get("has_lair", 0.0) > 0.5:
            r += 1.0
        if prev.get("has_hive", 0.0) < 0.5 and cur.get("has_hive", 0.0) > 0.5:
            r += 2.0

        prev_up = prev.get("melee_level", 0.0) + prev.get("missile_level", 0.0) + prev.get("ground_armor_level", 0.0)
        cur_up = cur.get("melee_level", 0.0) + cur.get("missile_level", 0.0) + cur.get("ground_armor_level", 0.0)
        r += 0.7 * max(0.0, cur_up - prev_up)

        for k in ["has_lurker_den", "has_infestation_pit", "has_spire", "has_ultra_cavern", "has_greater_spire"]:
            if prev.get(k, 0.0) < 0.5 and cur.get(k, 0.0) > 0.5:
                r += 0.45

        # -----------------------------------------------------------------------------------------
        # 侦察。
        # -----------------------------------------------------------------------------------------

        if prev.get("enemy_nat_seen", 0.0) < 0.5 and cur.get("enemy_nat_seen", 0.0) > 0.5:
            r += 0.35
        if prev.get("enemy_third_seen", 0.0) < 0.5 and cur.get("enemy_third_seen", 0.0) > 0.5:
            r += 0.5
        if cur.get("enemy_tech_seen_count", 0.0) > prev.get("enemy_tech_seen_count", 0.0):
            r += 0.2
        if cur.get("scout_info_age", 999.0) < prev.get("scout_info_age", 999.0) - 20:
            r += 0.12

        # -----------------------------------------------------------------------------------------
        # 资源管理。
        # -----------------------------------------------------------------------------------------

        if cur.get("gas_starved", 0.0) > 0.5:
            r -= 0.18
        if cur.get("gas_economy_emergency", 0.0) > 0.5:
            # This is the exact late-game failure: huge minerals, nearly no gas.
            # It must be much louder than normal bank-too-high shaping.
            r -= 0.85
            if a in {"ECON_MACRO", "FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS"}:
                r += 0.25
            if a in {"DO_NOTHING", "LING_PRESSURE", "ROACH_PRESSURE", "SCOUT_FOCUS"}:
                r -= 0.35
        if cur.get("gas_worker_debt", 0.0) > 3.0 and cur.get("game_time", 0.0) >= 300:
            r -= min(0.45, 0.04 * cur.get("gas_worker_debt", 0.0))
        if cur.get("bank_too_high", 0.0) > 0.5 and cur.get("supply_used", 0.0) < 190:
            r -= 0.22

        if cur.get("supply_left", 0.0) <= 0 and cur.get("supply_used", 0.0) < 195:
            r -= 0.16

        # -----------------------------------------------------------------------------------------
        # 当前兵种计划的组成一致性。
        # -----------------------------------------------------------------------------------------

        main_ratio_delta = cur.get("plan_main_ratio", 0.0) - prev.get("plan_main_ratio", 0.0)
        offplan_ratio = float(cur.get("plan_offplan_ratio", 0.0) or 0.0)
        support_overcap = float(cur.get("plan_support_overcap", 0.0) or 0.0)
        if cur.get("army_supply", 0.0) >= 45:
            r += max(-0.12, min(0.20, 0.8 * main_ratio_delta))
            # Do not punish early leftover lings/roaches too hard, but punish scattered late comps.
            if cur.get("game_time", 0.0) >= 420 and offplan_ratio > 0.30:
                r -= min(0.55, 0.55 * (offplan_ratio - 0.30))
            if support_overcap > 0:
                r -= min(0.50, 0.035 * support_overcap)

        tech_missing_delta = prev.get("plan_tech_missing_count", 0.0) - cur.get("plan_tech_missing_count", 0.0)
        upgrade_missing_delta = prev.get("plan_upgrade_missing_count", 0.0) - cur.get("plan_upgrade_missing_count", 0.0)
        gas_debt_delta = prev.get("plan_gas_debt", 0.0) - cur.get("plan_gas_debt", 0.0)
        if tech_missing_delta > 0:
            r += 0.55 * min(2.0, tech_missing_delta)
        if upgrade_missing_delta > 0:
            r += 0.22 * min(3.0, upgrade_missing_delta)
        if gas_debt_delta > 0:
            r += 0.08 * min(4.0, gas_debt_delta)
        gas_worker_debt_delta = prev.get("gas_worker_debt", 0.0) - cur.get("gas_worker_debt", 0.0)
        if gas_worker_debt_delta > 0:
            r += 0.06 * min(8.0, gas_worker_debt_delta)

        # v2.7 plan-consistency curriculum.  A plan is not a label; it must produce
        # required tech, gas, and main units.  This is the key fix for summaries like:
        # plan=brood_corruptor_viper, hive=False, main/off=0.0/0.89.
        plan_unrealized = float(cur.get("plan_unrealized", 0.0) or 0.0)
        plan_stuck = float(cur.get("plan_stuck", 0.0) or 0.0)
        if plan_unrealized > 0.5:
            r -= 0.35
            if a in {"FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS", "ECON_MACRO"}:
                r += 0.22
            if a in {"DO_NOTHING", "MAXED_ATTACK", "LING_PRESSURE"}:
                r -= 0.35
        if plan_stuck > 0.5:
            r -= 0.55
            if a in {"FAST_HIVE_TECH", "FAST_LAIR_TECH"}:
                r += 0.48
            if a == "DO_NOTHING":
                r -= 0.75

        # Late selected plan without Hive should strongly prefer tech-chain actions.
        if cur.get("plan_needs_hive", 0.0) > 0.5 and cur.get("has_hive", 0.0) < 0.5 and cur.get("game_time", 0.0) >= 520:
            if a == "FAST_HIVE_TECH":
                r += 0.42
            elif a in {"DO_NOTHING", "MAXED_ATTACK", "LING_PRESSURE", "ROACH_PRESSURE"}:
                r -= 0.32

        # -----------------------------------------------------------------------------------------
        # 战斗人口与战略意图一致性。
        # -----------------------------------------------------------------------------------------

        army_delta = cur.get("army_supply", 0.0) - prev.get("army_supply", 0.0)
        if cur.get("worker_count", 0.0) >= cur.get("worker_floor", 0.0):
            r += 0.018 * max(-6.0, min(10.0, army_delta))
        elif army_delta > 0:
            # worker floor 不满足还暴兵，扣。
            r -= 0.05 * min(10.0, army_delta)

        t = cur.get("game_time", 0.0)
        workers = cur.get("worker_count", 0.0)
        army = cur.get("army_supply", 0.0)
        lings = cur.get("zergling_count", 0.0)

        # 意图一致性：先选 intent，再造对应东西。
        if a == "LING_PRESSURE":
            # 选择狗压制，则狗数量增加和早期出门倾向是合理的。
            if t < 420:
                r += 0.05
            if cur.get("zergling_count", 0.0) > prev.get("zergling_count", 0.0):
                r += 0.08
            if army >= 18 and executed_ok:
                r += 0.12
            # 但压制 intent 不能拖成无进攻的低农中后期。
            if t > 420 or workers > 50:
                r -= 0.35

        elif a == "ECON_MACRO":
            if workers < min(cur.get("ideal_worker_total", 0.0), 82):
                if worker_delta > 0:
                    r += 0.12
            if army > 80 and workers < cur.get("worker_floor", 0.0):
                r -= 0.25

        elif a == "FAST_HIVE_TECH":
            if cur.get("has_infestation_pit", 0.0) > prev.get("has_infestation_pit", 0.0):
                r += 0.5
            if cur.get("has_hive", 0.0) > prev.get("has_hive", 0.0):
                r += 1.0
            if cur.get("gas_starved", 0.0) > 0.5:
                r -= 0.12

        elif a == "ROACH_HYDRA_TIMING":
            # Historical name kept for checkpoint/action compatibility; in v2.4 this means
            # "current army-plan production/timing", not literally roach-hydra only.
            main_delta = cur.get("plan_main_unit_count", 0.0) - prev.get("plan_main_unit_count", 0.0)
            if main_delta > 0:
                r += 0.10
            if cur.get("timing_attack_due", 0.0) > 0.5 and executed_ok:
                r += 0.35

        elif a == "SCOUT_FOCUS":
            if cur.get("scout_info_age", 999.0) < prev.get("scout_info_age", 999.0):
                r += 0.08

        elif a == "MAXED_ATTACK":
            if cur.get("supply_used", 0.0) >= 185 or cur.get("army_supply", 0.0) >= 80:
                r += 0.15
            else:
                r -= 0.2

        # v2.4/v2.7: explicit competition rhythm shaping.
        if stage == "defense":
            if a == "DEFENSIVE_HOLD":
                r += 0.55
            elif a in {"DO_NOTHING", "SCOUT_FOCUS", "FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS", "MAXED_ATTACK"}:
                r -= 0.55
        elif stage == "plan_setup":
            if a in {"FAST_LAIR_TECH", "FAST_HIVE_TECH", "UPGRADE_FOCUS", "ECON_MACRO"}:
                r += 0.30
            elif a == "DO_NOTHING":
                r -= 0.55

        if stage == "timing_attack":
            if a in {"ROACH_HYDRA_TIMING", "MAXED_ATTACK"}:
                r += 0.42
            elif a in {"ECON_MACRO", "DO_NOTHING"} and cur.get("supply_used", 0.0) >= 180:
                r -= 0.55
        elif stage == "late_transition":
            if a == "FAST_HIVE_TECH":
                r += 0.42
            elif a in {"LING_PRESSURE", "ROACH_PRESSURE", "DO_NOTHING"}:
                r -= 0.35
        elif stage == "map_hunt":
            if a in {"MAXED_ATTACK", "SCOUT_FOCUS"}:
                r += 0.35
            elif a in {"ECON_MACRO", "DO_NOTHING"}:
                r -= 0.35
        elif stage == "scout":
            if a == "SCOUT_FOCUS":
                r += 0.28
            elif cur.get("scout_info_age", 999.0) >= 120 and a in {"FAST_HIVE_TECH", "FAST_LAIR_TECH", "UPGRADE_FOCUS"}:
                # Teching blindly with stale information is how it ends up with one-of-everything.
                r -= 0.22

        if cur.get("supply_used", 0.0) >= 198 and a in {"ECON_MACRO", "DO_NOTHING"} and cur.get("expand_debt", 0.0) < 0.5:
            r -= 0.85

        # 没有 intent 的大量狗闲置：不是用狗数量反推压制，而是惩罚“非压制 intent 下的矛盾状态”。
        if a not in {"LING_PRESSURE", "DEFENSIVE_HOLD"} and t < 360 and lings >= 20 and army >= 20:
            r -= 0.12

        # 经济结构硬约束：主矿/单基地过饱和是运营 0 分信号。
        # v2.2 fix: bases / pending_bases 必须从当前观测里取。
        # 之前这里直接使用未定义变量 bases，会在 RL 第一次接管后的第二次 reward 计算时 NameError，
        # 导致 SC2 连接被 python-sc2 关闭，看起来像“四分多钟直接退”。
        bases = float(cur.get("base_count", 0.0) or 0.0)
        pending_bases = float(cur.get("pending_base_count", 0.0) or 0.0)
        total_bases = bases + pending_bases

        max_over = float(cur.get("max_base_overflow", 0.0) or 0.0)
        overflow_total = float(cur.get("worker_overflow_total", 0.0) or 0.0)
        underflow_total = float(cur.get("worker_underflow_total", 0.0) or 0.0)
        if max_over >= 4:
            r -= 0.035 * (max_over ** 2)
        if overflow_total > 0:
            r -= 0.012 * (overflow_total ** 2)
        if underflow_total >= 8 and bases >= 3:
            r -= 0.015 * underflow_total
        if t >= 270 and total_bases < 3:
            r -= 0.40
        if t >= 360 and total_bases < 3:
            r -= 1.20
        if t >= 450 and total_bases < 4:
            r -= 0.60

        # 12 分钟 6 基地 200 人口还没 Hive 是典型“不会转型”。
        if t >= 660 and cur.get("base_count", 0.0) >= 4 and cur.get("worker_count", 0.0) >= 72 and cur.get("has_hive", 0.0) < 0.5:
            if a == "FAST_HIVE_TECH":
                r += 0.35
            else:
                r -= 0.24

        # 动作执行反馈。
        if not executed_ok and a not in {"DO_NOTHING", "SCOUT_FOCUS"}:
            r -= 0.10
        elif executed_ok and a != "DO_NOTHING":
            r += 0.03

        # 过早低农暴兵。
        if t < 480 and workers < 55 and army > 70 and a not in {"LING_PRESSURE", "ROACH_PRESSURE"}:
            r -= 0.35

        return float(max(-5.0, min(5.0, r)))

    def terminal_reward(self, result) -> float:
        text = str(result).lower()
        if "victory" in text or "win" in text or "inferredvictory" in text or "enemy_gg" in text:
            return 30.0
        if "resigneddefeat" in text:
            return -25.0
        if "defeat" in text or "loss" in text:
            return -30.0
        # Connection closed but no result: do not train it as a loss.
        if "unknownconnectionclosed" in text or "connectionclosed" in text:
            return 0.0
        return 0.0
