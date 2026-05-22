# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def summarize_episode(ep_dir: Path) -> Dict[str, object]:
    # v0.2 默认只写 summary，不写 steps。
    summary_file = ep_dir / "rl_logs" / "episode_summary.json"
    summary = load_json(summary_file)
    if summary:
        final = summary.get("final", {}) or {}
        return {
            "episode": ep_dir.name,
            "steps": summary.get("steps", 0),
            "result": summary.get("result"),
            "reward_sum": summary.get("reward_sum_with_terminal"),
            "final_time": final.get("time_sec"),
            "workers": final.get("workers"),
            "worker_floor": final.get("worker_floor"),
            "worker_overflow_total": final.get("worker_overflow_total"),
            "max_base_overflow": final.get("max_base_overflow"),
            "avg_saturation_error": final.get("avg_saturation_error"),
            "enemy_gg_seen": final.get("enemy_gg_seen"),
            "last_intent": final.get("last_intent"),
            "army_supply": final.get("army_supply"),
            "bases": final.get("bases"),
            "pending_bases": final.get("pending_bases"),
            "supply": f"{final.get('supply_used', 0)}/{final.get('supply_cap', 0)}",
            "hive": final.get("has_hive"),
            "gas": final.get("vespene"),
            "minerals": final.get("minerals"),
            "top_actions": summary.get("top_actions", [])[:5],
            "update": summary.get("update", {}),
        }

    # 兼容旧版：从 step log 统计。
    step_file = ep_dir / "rl_logs" / "rl_episode_steps.jsonl"
    sum_file = ep_dir / "rl_logs" / "rl_episode_summary.jsonl"
    steps = load_jsonl(step_file)
    summaries = load_jsonl(sum_file)
    if not steps:
        return {"episode": ep_dir.name, "steps": 0, "status": "no summary/steps found"}

    last = steps[-1].get("obs", {})
    action_counts = {}
    reward_sum = 0.0
    for r in steps:
        a = r.get("action_name", "UNKNOWN")
        action_counts[a] = action_counts.get(a, 0) + 1
        reward_sum += float(r.get("reward_from_prev", 0.0) or 0.0)

    return {
        "episode": ep_dir.name,
        "steps": len(steps),
        "result": summaries[-1].get("result") if summaries else None,
        "reward_sum": round(reward_sum, 3),
        "final_time": round(float(last.get("game_time", 0.0)), 1),
        "workers": last.get("worker_count"),
        "worker_floor": last.get("worker_floor"),
        "army_supply": last.get("army_supply"),
        "bases": last.get("base_count"),
        "pending_bases": last.get("pending_base_count"),
        "supply": f"{int(last.get('supply_used', 0))}/{int(last.get('supply_cap', 0))}",
        "hive": last.get("has_hive"),
        "gas": last.get("vespene"),
        "minerals": last.get("minerals"),
        "top_actions": sorted(action_counts.items(), key=lambda x: x[1], reverse=True)[:5],
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze Macro-RL summary logs")
    parser.add_argument("--run-dir", default="runs_v28")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    run_dir = (root / args.run_dir).resolve()
    eps = sorted([p for p in run_dir.glob("episode_*") if p.is_dir()])
    if not eps:
        print(f"No episodes found in {run_dir}")
        return

    rows = [summarize_episode(p) for p in eps]
    for r in rows:
        print("=" * 100)
        for k, v in r.items():
            print(f"{k:14s}: {v}")


if __name__ == "__main__":
    main()
