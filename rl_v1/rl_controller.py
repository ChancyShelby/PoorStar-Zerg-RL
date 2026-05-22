# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Optional

from rl_v1.agent import MacroAgent, Transition
from rl_v1.macro_actions import ACTION_NAMES, MacroActionExecutor, make_action_mask
from rl_v1.reward import RewardComputer
from rl_v1.state_features import extract_observation, vectorize_observation


class RLController:
    """
    Macro-RL v1 控制器。

    v0.2 no-log 改动：
    - 默认不写每一步 rl_episode_steps.jsonl。
    - 训练 trajectory 仍保存在内存里，episode 结束时正常 update。
    - 只写很小的 episode_summary.json，避免边跑边刷磁盘导致卡顿。
    """

    def __init__(
        self,
        bot,
        agent: MacroAgent,
        log_dir: Path | str,
        rl_start_time: float = 240.0,
        rl_decision_interval: float = 10.0,
        train: bool = True,
        greedy: bool = False,
        write_step_log: bool = False,
        write_summary: bool = True,
        training_profile: str = "balanced",
    ):
        self.bot = bot
        self.agent = agent
        self.log_dir = Path(log_dir)
        self.write_step_log = bool(write_step_log)
        self.write_summary = bool(write_summary)
        if self.write_step_log or self.write_summary:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        self.rl_start_time = float(rl_start_time)
        self.rl_decision_interval = float(rl_decision_interval)
        self.train = bool(train)
        self.greedy = bool(greedy)
        self.training_profile = str(training_profile or "balanced")
        self.finished = False

        self.macro_executor = MacroActionExecutor(bot)
        self.rewarder = RewardComputer()

        self.last_decision_time = -999.0
        self.prev_obs = None
        self.prev_state_vec = None
        self.prev_action = None
        self.prev_mask = None
        self.prev_action_name = None
        self.prev_exec = None

        self.episode_log_path = self.log_dir / "rl_episode_steps.jsonl"
        self.summary_json_path = self.log_dir / "episode_summary.json"
        self.summary_log_path = self.log_dir / "rl_episode_summary.jsonl"
        self.step_f = None
        if self.write_step_log:
            self.step_f = self.episode_log_path.open("a", encoding="utf-8")

        self.step_count = 0
        self.reward_sum = 0.0
        self.action_counts: Counter[str] = Counter()
        self.exec_ok_counts: Counter[str] = Counter()
        self.last_obs = None
        self.last_policy_info = None
        self.last_exec_reason = ""
        self.last_reward_error = ""

    def _safe_current_observation(self) -> dict:
        """Return the freshest observation available for terminal summaries.

        During normal on_end / resign handling the bot is still alive, so we should
        re-extract the current observation instead of reusing self.last_obs.  Reusing
        self.last_obs can make the summary show an old healthy state while the
        resign detector used the current collapsed state.  If SC2 has already closed
        the connection, fall back to the last cached observation.
        """
        try:
            obs = extract_observation(self.bot)
            if isinstance(obs, dict):
                self.last_obs = obs
                return obs
        except Exception as exc:
            err = f"final_obs_extract_failed: {type(exc).__name__}: {exc}"
            self.last_reward_error = err if not self.last_reward_error else f"{self.last_reward_error} | {err}"
        return self.last_obs or {}

    async def maybe_step(self, iteration: int):
        now = float(getattr(self.bot, "time", 0.0))
        if now < self.rl_start_time:
            return None
        if now - self.last_decision_time < self.rl_decision_interval:
            return None
        self.last_decision_time = now

        obs = extract_observation(self.bot)
        state_vec = vectorize_observation(obs)

        # 1. 关闭上一条 transition。
        if self.prev_obs is not None:
            try:
                reward = self.rewarder.step_reward(
                    prev=self.prev_obs,
                    cur=obs,
                    action_name=self.prev_action_name or "UNKNOWN",
                    executed_ok=bool(self.prev_exec.ok) if self.prev_exec is not None else False,
                )
                self.last_reward_error = ""
            except Exception as exc:
                # v2.2 safety: reward shaping 不能因为一个变量名/边界 bug 直接杀掉整局 SC2。
                # 这种错误只给轻微负分并继续跑；summary 会记录 reward_error，方便回头修。
                reward = -0.25
                self.last_reward_error = f"{type(exc).__name__}: {exc}"
                if self.write_step_log:
                    self.last_reward_error += "\n" + traceback.format_exc(limit=3)
            self.reward_sum += float(reward)
            if self.train:
                self.agent.add_transition(
                    Transition(
                        state=self.prev_state_vec,
                        action=int(self.prev_action),
                        reward=float(reward),
                        mask=list(self.prev_mask),
                        action_name=str(self.prev_action_name),
                        executed_ok=bool(self.prev_exec.ok) if self.prev_exec is not None else False,
                        primitive_action=str(self.prev_exec.primitive_action) if self.prev_exec is not None else "",
                        reason=str(self.prev_exec.reason) if self.prev_exec is not None else "",
                        time_sec=float(now),
                    )
                )
        else:
            reward = 0.0

        # 2. 当前 state 选动作。
        mask = make_action_mask(obs, profile=self.training_profile)
        action_idx, policy_info = self.agent.act(state_vec, mask=mask, greedy=(self.greedy or not self.train))
        action_name = ACTION_NAMES[action_idx]
        exec_res = await self.macro_executor.execute(action_idx)

        self.step_count += 1
        self.action_counts[action_name] += 1
        if exec_res.ok:
            self.exec_ok_counts[action_name] += 1
        self.last_obs = obs
        self.last_policy_info = policy_info
        self.last_exec_reason = str(exec_res.reason)

        if self.write_step_log and self.step_f is not None:
            record = {
                "time_sec": now,
                "iteration": int(iteration),
                "reward_from_prev": float(reward),
                "action_idx": int(action_idx),
                "action_name": action_name,
                "exec": exec_res.to_dict(),
                "policy": policy_info,
                "mask": {ACTION_NAMES[i]: float(mask[i]) for i in range(len(ACTION_NAMES))},
                "obs": obs,
            }
            self.step_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            # 这里不再每步 flush，减少磁盘 I/O。episode 结束统一 flush/close。

        # 3. 缓存当前决策，下一次计算 reward。
        self.prev_obs = obs
        self.prev_state_vec = state_vec
        self.prev_action = action_idx
        self.prev_mask = mask
        self.prev_action_name = action_name
        self.prev_exec = exec_res

        return exec_res if exec_res.consumed_turn else None


    def _normalize_result(self, result) -> str:
        """Convert SC2 result/exception into a stable training label."""
        text = str(result)
        # If we saw enemy GG chat, trust it even if python-sc2 did not return Result.Victory.
        if bool(getattr(self.bot, "enemy_gg_seen", False)):
            return "InferredVictory(enemy_gg)"
        low = text.lower()
        if "victory" in low or "defeat" in low:
            return text
        if "cannot write to closing transport" in low or "connection" in low:
            return "UnknownConnectionClosed"
        return text

    def finish_episode(self, result) -> dict:
        if self.finished:
            # Protect against on_end firing after an intentional resign/leave.
            final_obs = self._safe_current_observation()
            return {
                "result": self._normalize_result(result),
                "terminal_reward": 0.0,
                "train": self.train,
                "steps": int(self.step_count),
                "reward_sum_without_terminal": round(float(self.reward_sum), 4),
                "reward_sum_with_terminal": round(float(self.reward_sum), 4),
                "update": {"updated": 0, "reason": "already finished"},
                "final": {"time_sec": round(float(final_obs.get("game_time", 0.0)), 1)},
                "top_actions": self.action_counts.most_common(8),
                "exec_ok_actions": dict(self.exec_ok_counts),
                "last_exec_reason": self.last_exec_reason,
            }
        self.finished = True
        result_text = self._normalize_result(result)
        terminal = self.rewarder.terminal_reward(result_text)
        if self.step_f:
            self.step_f.flush()
            self.step_f.close()
            self.step_f = None

        update_summary = {"updated": 0, "reason": "eval mode"}
        if self.train:
            update_summary = self.agent.update(terminal_reward=terminal)
        else:
            self.agent.clear_episode()

        final_obs = self._safe_current_observation()
        try:
            from rl_v1.strategic_stage import infer_stage
            final_stage = infer_stage(final_obs)
        except Exception:
            final_stage = "unknown"
        top_actions = self.action_counts.most_common(8)
        ok_actions = dict(self.exec_ok_counts)
        summary = {
            "result": result_text,
            "terminal_reward": float(terminal),
            "train": self.train,
            "steps": int(self.step_count),
            "reward_sum_without_terminal": round(float(self.reward_sum), 4),
            "reward_sum_with_terminal": round(float(self.reward_sum + terminal), 4),
            "update": update_summary,
            "final": {
                "time_sec": round(float(final_obs.get("game_time", 0.0)), 1),
                "workers": int(final_obs.get("worker_count", 0) or 0),
                "worker_floor": int(final_obs.get("worker_floor", 0) or 0),
                "army_supply": float(final_obs.get("army_supply", 0.0) or 0.0),
                "bases": int(final_obs.get("base_count", 0) or 0),
                "pending_bases": int(final_obs.get("pending_base_count", 0) or 0),
                "supply_used": int(final_obs.get("supply_used", 0) or 0),
                "supply_cap": int(final_obs.get("supply_cap", 0) or 0),
                "minerals": int(final_obs.get("minerals", 0) or 0),
                "vespene": int(final_obs.get("vespene", 0) or 0),
                "has_lair": bool(final_obs.get("has_lair", False)),
                "has_hive": bool(final_obs.get("has_hive", False)),
                "gas_count": int(final_obs.get("total_gas_count", 0) or 0),
                "ready_gas_count": int(final_obs.get("ready_gas_count", 0) or 0),
                "gas_worker_count": int(final_obs.get("gas_worker_count", 0) or 0),
                "gas_worker_target": int(final_obs.get("gas_worker_target", 0) or 0),
                "gas_worker_debt": int(final_obs.get("gas_worker_debt", 0) or 0),
                "gas_economy_emergency": bool(final_obs.get("gas_economy_emergency", 0.0) > 0.5),
                "mineral_gas_ratio": round(float(final_obs.get("mineral_gas_ratio", 0.0) or 0.0), 2),
                "ideal_worker_total": int(final_obs.get("ideal_worker_total", 0) or 0),
                "assigned_mineral_workers_total": int(final_obs.get("assigned_mineral_workers_total", 0) or 0),
                "worker_overflow_total": int(final_obs.get("worker_overflow_total", 0) or 0),
                "worker_underflow_total": int(final_obs.get("worker_underflow_total", 0) or 0),
                "max_base_overflow": int(final_obs.get("max_base_overflow", 0) or 0),
                "avg_saturation_error": round(float(final_obs.get("avg_saturation_error", 0) or 0.0), 3),
                "enemy_gg_seen": bool(getattr(self.bot, "enemy_gg_seen", False)),
                "last_intent": str(getattr(self.bot, "rl_current_intent", "")),
                "training_profile": self.training_profile,
                "last_reward_error": self.last_reward_error,
                "resigned": bool(getattr(self.bot, "_resign_triggered", False)),
                "resign_reason": str(getattr(self.bot, "_resign_reason", "")),
                "army_plan": str(getattr(self.bot, "rl_army_plan", "")),
                "army_plan_reason": str(getattr(self.bot, "rl_army_plan_reason", "")),
                "strategic_stage": final_stage,
                "worker_target_cap": int(final_obs.get("worker_target_cap", 0) or 0),
                "worker_excess": int(final_obs.get("worker_excess", 0) or 0),
                "plan_main_ratio": round(float(final_obs.get("plan_main_ratio", 0.0) or 0.0), 3),
                "plan_offplan_ratio": round(float(final_obs.get("plan_offplan_ratio", 0.0) or 0.0), 3),
                "plan_tech_missing_count": int(final_obs.get("plan_tech_missing_count", 0) or 0),
                "plan_upgrade_missing_count": int(final_obs.get("plan_upgrade_missing_count", 0) or 0),
                "plan_age": round(float(final_obs.get("plan_age", 0.0) or 0.0), 1),
                "plan_unrealized": bool(final_obs.get("plan_unrealized", 0.0) > 0.5),
                "plan_stuck": bool(final_obs.get("plan_stuck", 0.0) > 0.5),
                "scout_due": bool(final_obs.get("scout_due", 0.0) > 0.5),
                "timing_attack_due": bool(final_obs.get("timing_attack_due", 0.0) > 0.5),
                "late_transition_due": bool(final_obs.get("late_transition_due", 0.0) > 0.5),
                "map_hunt_due": bool(final_obs.get("map_hunt_due", 0.0) > 0.5),
            },
            "top_actions": top_actions,
            "exec_ok_actions": ok_actions,
            "last_exec_reason": self.last_exec_reason,
        }
        if self.write_summary:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with self.summary_json_path.open("w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            # 小 jsonl，方便 analyze 聚合；每局只写一行，不影响性能。
            with self.summary_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return summary
