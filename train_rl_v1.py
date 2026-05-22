# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_baseline_to_path(baseline_dir: Path):
    baseline_dir = baseline_dir.resolve()
    if not baseline_dir.exists():
        raise FileNotFoundError(f"baseline_dir not found: {baseline_dir}")
    sys.path.insert(0, str(baseline_dir))


def race_from_string(s: str):
    from sc2.data import Race
    key = str(s).strip().lower()
    table = {
        "zerg": Race.Zerg,
        "terran": Race.Terran,
        "protoss": Race.Protoss,
        "random": Race.Random,
    }
    if key not in table:
        raise ValueError(f"Unknown race: {s}")
    return table[key]


def difficulty_from_string(s: str):
    from sc2.data import Difficulty
    table = {
        "veryeasy": Difficulty.VeryEasy,
        "easy": Difficulty.Easy,
        "medium": Difficulty.Medium,
        "mediumhard": Difficulty.MediumHard,
        "hard": Difficulty.Hard,
        "harder": Difficulty.Harder,
        "veryhard": Difficulty.VeryHard,
        "cheatvision": Difficulty.CheatVision,
        "cheatmoney": Difficulty.CheatMoney,
        "cheatinsane": Difficulty.CheatInsane,
    }
    key = str(s).strip().replace("_", "").replace("-", "").lower()
    if key not in table:
        raise ValueError(f"Unknown difficulty: {s}")
    return table[key]


def maybe_suppress_stdout(enabled: bool):
    import contextlib
    import os
    if not enabled:
        return contextlib.nullcontext()
    devnull = open(os.devnull, "w", encoding="utf-8")
    return contextlib.redirect_stdout(devnull)


def compact_episode_summary(summary: dict | None) -> str:
    if not summary:
        return "summary unavailable"
    final = summary.get("final", {}) or {}
    top_actions = summary.get("top_actions", []) or []
    top_txt = ", ".join([f"{a}:{n}" for a, n in top_actions[:5]]) if top_actions else "none"
    return (
        f"result={summary.get('result')} | "
        f"steps={summary.get('steps')} | "
        f"reward={summary.get('reward_sum_with_terminal')} | "
        f"time={final.get('time_sec')} | "
        f"workers={final.get('workers')}/{final.get('worker_floor')} | "
        f"sat_over={final.get('worker_overflow_total', 0)} max_over={final.get('max_base_overflow', 0)} | "
        f"army={final.get('army_supply')} | "
        f"bases={final.get('bases')}+{final.get('pending_bases')}p | "
        f"supply={final.get('supply_used')}/{final.get('supply_cap')} | "
        f"hive={final.get('has_hive')} | "
        f"bank={final.get('minerals')}/{final.get('vespene')} | "
        f"top_actions=[{top_txt}]"
    )


def main():
    parser = argparse.ArgumentParser(description="Train PoorStar Macro-RL v1.2 no-log version")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--map", default="AutomatonLE")
    parser.add_argument("--enemy-race", default="Zerg", choices=["Zerg", "Terran", "Protoss", "Random"])
    parser.add_argument("--difficulty", default="VeryHard", help="Recommended: VeryHard first; use CheatInsane only for stress testing.")
    parser.add_argument("--baseline-dir", default=r"baseline\PoorStar_v1_23_workerflow_baseline")
    parser.add_argument("--model-dir", default=r"baseline\PoorStar_v1_23_workerflow_baseline\models\16H_extractor_trick_hatch_first")
    parser.add_argument("--checkpoint-dir", default="checkpoints")
    parser.add_argument("--run-dir", default="runs")
    parser.add_argument("--opening-time", type=float, default=240.0)
    parser.add_argument("--decision-interval", type=float, default=1.0)
    parser.add_argument("--rl-start-time", type=float, default=240.0)
    parser.add_argument("--rl-decision-interval", type=float, default=10.0)
    parser.add_argument("--training-profile", default="economy", choices=["economy", "balanced"], help="economy: macro-economy curriculum; balanced: allow all strategic intents")
    parser.add_argument("--disable-resign", action="store_true", help="disable early resign detector")
    parser.add_argument("--disable-advanced-control", action="store_true", help="disable basic viper/infestor/lurker support control")
    parser.add_argument("--disable-economy-support", action="store_true", help="disable automatic worker transfer from oversaturated bases")
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--device", default="auto", help="auto/cpu/cuda. GPU only accelerates the tiny RL network, not the SC2 simulation.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--resume", action="store_true", help="load checkpoints/macro_policy_latest.pt if exists")
    parser.add_argument("--verbose", action="store_true", help="show all PoorStar step prints. Default is quiet/no per-step console output.")
    parser.add_argument("--write-step-logs", action="store_true", help="write rl_episode_steps.jsonl. Slow; disabled by default.")
    parser.add_argument("--write-poorstar-logs", action="store_true", help="write PoorStar per-step jsonl. Slow; disabled by default.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    baseline_dir = (root / args.baseline_dir).resolve()
    model_dir = (root / args.model_dir).resolve()
    checkpoint_dir = (root / args.checkpoint_dir).resolve()
    run_root = (root / args.run_dir).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    aggregate_summary_path = run_root / "training_summary.jsonl"

    add_baseline_to_path(baseline_dir)

    from sc2 import maps
    from sc2.data import Race
    from sc2.main import run_game
    from sc2.player import Bot, Computer

    from rl_v1.agent import MacroAgent
    from rl_v1.rl_bot import RLPoorStarBot
    from rl_v1.state_features import FEATURE_DIM

    agent = MacroAgent(
        obs_dim=FEATURE_DIM,
        checkpoint_dir=checkpoint_dir,
        lr=args.lr,
        gamma=args.gamma,
        device=args.device,
        seed=args.seed,
    )
    if args.resume:
        loaded = agent.load_if_exists()
        print(f"[RL] resume checkpoint: {loaded} -> {agent.latest_path}")

    print("=" * 100)
    print("TRAIN MACRO-RL V1.2 NO-LOG")
    print(f"episodes             : {args.episodes}")
    print(f"map                  : {args.map}")
    print(f"enemy                : {args.enemy_race} {args.difficulty}")
    print(f"device               : {agent.device}")
    print(f"baseline_dir         : {baseline_dir}")
    print(f"model_dir            : {model_dir}")
    print(f"checkpoint_dir       : {checkpoint_dir}")
    print(f"run_root             : {run_root}")
    print(f"rl_decision_interval : {args.rl_decision_interval}")
    print(f"training_profile     : {args.training_profile}")
    print(f"enable_resign        : {not args.disable_resign}")
    print(f"enable_adv_control   : {not args.disable_advanced_control}")
    print(f"enable_econ_support  : {not args.disable_economy_support}")
    print(f"quiet                : {not args.verbose}")
    print(f"write_step_logs      : {args.write_step_logs}")
    print(f"write_poorstar_logs  : {args.write_poorstar_logs}")
    print("=" * 100)

    for ep in range(1, args.episodes + 1):
        ep_dir = run_root / f"episode_{ep:04d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        bot = RLPoorStarBot(
            model_dir=model_dir,
            agent=agent,
            opening_time=args.opening_time,
            decision_interval=args.decision_interval,
            topk=args.topk,
            enable_safety=True,
            enable_rule_after_opening=True,
            log_dir=ep_dir,
            rl_start_time=args.rl_start_time,
            rl_decision_interval=args.rl_decision_interval,
            train_rl=True,
            greedy_rl=False,
            quiet=(not args.verbose),
            write_poorstar_log=args.write_poorstar_logs,
            write_rl_step_log=args.write_step_logs,
            write_summary=True,
            enable_resign=(not args.disable_resign),
            enable_advanced_unit_control=(not args.disable_advanced_control),
            enable_economy_support=(not args.disable_economy_support),
            training_profile=args.training_profile,
        )
        print("=" * 100)
        print(f"EPISODE {ep}/{args.episodes} | enemy={args.enemy_race} {args.difficulty} | dir={ep_dir}")
        print("=" * 100)
        try:
            with maybe_suppress_stdout(enabled=(not args.verbose)):
                run_game(
                    maps.get(args.map),
                    [
                        Bot(Race.Zerg, bot),
                        Computer(race_from_string(args.enemy_race), difficulty_from_string(args.difficulty)),
                    ],
                    realtime=args.realtime,
                )
        except KeyboardInterrupt:
            print("Training interrupted by user.")
            agent.save()
            raise
        except Exception as exc:
            # SC2 occasionally closes websocket after match end. Keep training robust.
            print(f"[EPISODE {ep}] run_game exception: {type(exc).__name__}: {exc}")
            hint = "InferredVictory(enemy_gg)" if getattr(bot, "enemy_gg_seen", False) else f"UnknownConnectionClosed({type(exc).__name__})"
            try:
                bot.force_finish_episode(hint)
            except Exception:
                pass
            agent.save()

        summary = getattr(bot, "last_episode_summary", None)
        print(f"EPISODE {ep} SUMMARY: {compact_episode_summary(summary)}")
        if summary:
            with aggregate_summary_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"episode": ep, **summary}, ensure_ascii=False) + "\n")

    agent.save()
    print("=" * 100)
    print("TRAINING FINISHED")
    print(f"latest checkpoint: {agent.latest_path}")
    print(f"aggregate summary: {aggregate_summary_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()
