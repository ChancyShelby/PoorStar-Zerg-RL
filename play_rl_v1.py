# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
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
    return {"zerg": Race.Zerg, "terran": Race.Terran, "protoss": Race.Protoss, "random": Race.Random}[key]


def difficulty_from_string(s: str):
    from sc2.data import Difficulty
    key = str(s).strip().replace("_", "").replace("-", "").lower()
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
    parser = argparse.ArgumentParser(description="Play with trained PoorStar Macro-RL v1.2 checkpoint")
    parser.add_argument("--map", default="AutomatonLE")
    parser.add_argument("--enemy-race", default="Zerg", choices=["Zerg", "Terran", "Protoss", "Random"])
    parser.add_argument("--difficulty", default="VeryHard")
    parser.add_argument("--baseline-dir", default=r"baseline\PoorStar_v1_23_workerflow_baseline")
    parser.add_argument("--model-dir", default=r"baseline\PoorStar_v1_23_workerflow_baseline\models\16H_extractor_trick_hatch_first")
    parser.add_argument("--checkpoint", default=r"checkpoints\macro_policy_latest.pt")
    parser.add_argument("--run-dir", default="eval_runs")
    parser.add_argument("--rl-decision-interval", type=float, default=10.0)
    parser.add_argument("--training-profile", default="economy", choices=["economy", "balanced"], help="economy: macro-economy curriculum; balanced: allow all strategic intents")
    parser.add_argument("--disable-resign", action="store_true", help="disable early resign detector")
    parser.add_argument("--disable-advanced-control", action="store_true", help="disable basic viper/infestor/lurker support control")
    parser.add_argument("--disable-economy-support", action="store_true", help="disable automatic worker transfer from oversaturated bases")
    parser.add_argument("--opening-time", type=float, default=240.0)
    parser.add_argument("--decision-interval", type=float, default=1.0)
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--write-step-logs", action="store_true")
    parser.add_argument("--write-poorstar-logs", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    baseline_dir = (root / args.baseline_dir).resolve()
    model_dir = (root / args.model_dir).resolve()
    checkpoint = (root / args.checkpoint).resolve()
    run_dir = (root / args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    add_baseline_to_path(baseline_dir)

    from sc2 import maps
    from sc2.data import Race
    from sc2.main import run_game
    from sc2.player import Bot, Computer

    from rl_v1.agent import MacroAgent
    from rl_v1.rl_bot import RLPoorStarBot
    from rl_v1.state_features import FEATURE_DIM

    agent = MacroAgent(obs_dim=FEATURE_DIM, checkpoint_dir=root / "checkpoints", device=args.device)
    if checkpoint.exists():
        agent.load_if_exists(checkpoint)
        print(f"[RL] loaded checkpoint: {checkpoint}")
    else:
        print(f"[RL] checkpoint not found, running random/initial policy: {checkpoint}")
    print(f"[RL] device: {agent.device}")

    bot = RLPoorStarBot(
        model_dir=model_dir,
        agent=agent,
        opening_time=args.opening_time,
        decision_interval=args.decision_interval,
        topk=args.topk,
        enable_safety=True,
        enable_rule_after_opening=True,
        log_dir=run_dir,
        rl_start_time=args.opening_time,
        rl_decision_interval=args.rl_decision_interval,
        train_rl=False,
        greedy_rl=True,
        quiet=(not args.verbose),
        write_poorstar_log=args.write_poorstar_logs,
        write_rl_step_log=args.write_step_logs,
        write_summary=True,
    )

    with maybe_suppress_stdout(enabled=(not args.verbose)):
        run_game(
            maps.get(args.map),
            [Bot(Race.Zerg, bot), Computer(race_from_string(args.enemy_race), difficulty_from_string(args.difficulty))],
            realtime=args.realtime,
        )
    print(f"EVAL SUMMARY: {compact_episode_summary(getattr(bot, 'last_episode_summary', None))}")


if __name__ == "__main__":
    main()
