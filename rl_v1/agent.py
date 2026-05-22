# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical

from rl_v1.macro_actions import ACTION_DIM, ACTION_NAMES


class ActorCritic(nn.Module):
    def __init__(self, obs_dim: int, action_dim: int = ACTION_DIM, hidden_dim: int = 128):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
        )
        self.policy_head = nn.Linear(hidden_dim, action_dim)
        self.value_head = nn.Linear(hidden_dim, 1)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        h = self.trunk(x)
        logits = self.policy_head(h)
        value = self.value_head(h).squeeze(-1)
        return logits, value


@dataclass
class Transition:
    state: List[float]
    action: int
    reward: float
    mask: List[float]
    action_name: str
    executed_ok: bool
    primitive_action: str
    reason: str
    time_sec: float


class MacroAgent:
    """
    Macro-RL v1：轻量 Actor-Critic。

    这是第一版可跑通训练闭环的实现，不是最终 PPO。等 state/action/reward 稳了以后，
    可以把 update() 换成 PPO 多 epoch clipped objective。
    """

    def __init__(
        self,
        obs_dim: int,
        checkpoint_dir: Path | str,
        lr: float = 3e-4,
        gamma: float = 0.99,
        entropy_coef: float = 0.015,
        value_coef: float = 0.5,
        device: str = "cpu",
        seed: int = 42,
    ):
        self.obs_dim = int(obs_dim)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.gamma = float(gamma)
        self.entropy_coef = float(entropy_coef)
        self.value_coef = float(value_coef)
        self.device = self._resolve_device(device)
        self.rng = random.Random(seed)
        torch.manual_seed(seed)
        if self.device.type == "cuda":
            torch.cuda.manual_seed_all(seed)

        self.model = ActorCritic(obs_dim=self.obs_dim, action_dim=ACTION_DIM).to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        self.trajectory: List[Transition] = []
        self.update_count = 0
        self.latest_path = self.checkpoint_dir / "macro_policy_latest.pt"
        self.history_path = self.checkpoint_dir / "training_history.jsonl"

    @staticmethod
    def _resolve_device(device: str) -> torch.device:
        key = str(device or "auto").strip().lower()
        if key == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if key.startswith("cuda") and not torch.cuda.is_available():
            print("[RL] CUDA requested but not available; falling back to CPU.")
            return torch.device("cpu")
        return torch.device(key)

    def load_if_exists(self, path: Optional[Path | str] = None) -> bool:
        ckpt_path = Path(path) if path else self.latest_path
        if not ckpt_path.exists():
            return False
        data = torch.load(ckpt_path, map_location=self.device)

        # v1 的 action space 从“散装动作”改成“战略意图”，旧 v0 checkpoint 维度不兼容。
        old_actions = list(data.get("action_names", []))
        if old_actions and old_actions != ACTION_NAMES:
            print("[RL] checkpoint action space is incompatible; starting fresh.")
            print(f"[RL] old actions: {old_actions}")
            print(f"[RL] new actions: {ACTION_NAMES}")
            return False
        if int(data.get("obs_dim", self.obs_dim)) != int(self.obs_dim):
            print("[RL] checkpoint obs_dim is incompatible; starting fresh.")
            return False

        try:
            self.model.load_state_dict(data["model"])
            if "optimizer" in data:
                self.optimizer.load_state_dict(data["optimizer"])
            self.update_count = int(data.get("update_count", 0))
            return True
        except Exception as exc:
            print(f"[RL] checkpoint load failed ({type(exc).__name__}: {exc}); starting fresh.")
            return False

    def save(self, path: Optional[Path | str] = None) -> None:
        ckpt_path = Path(path) if path else self.latest_path
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model": self.model.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "obs_dim": self.obs_dim,
                "action_names": ACTION_NAMES,
                "update_count": self.update_count,
            },
            ckpt_path,
        )

    def act(self, state_vec: Sequence[float], mask: Sequence[float], greedy: bool = False) -> Tuple[int, Dict[str, float]]:
        self.model.eval()
        with torch.no_grad():
            x = torch.tensor([list(state_vec)], dtype=torch.float32, device=self.device)
            logits, value = self.model(x)
            mask_t = torch.tensor([list(mask)], dtype=torch.float32, device=self.device)
            masked_logits = logits.masked_fill(mask_t <= 0.0, -1e9)
            probs = F.softmax(masked_logits, dim=-1)
            if greedy:
                action = int(torch.argmax(probs, dim=-1).item())
            else:
                dist = Categorical(probs=probs)
                action = int(dist.sample().item())
            info = {
                "value": float(value.item()),
                "prob": float(probs[0, action].item()),
                "entropy": float(Categorical(probs=probs).entropy().item()),
            }
            for i, name in enumerate(ACTION_NAMES):
                info[f"p_{name}"] = float(probs[0, i].item())
            return action, info

    def add_transition(self, tr: Transition) -> None:
        self.trajectory.append(tr)

    def clear_episode(self) -> None:
        self.trajectory.clear()

    def update(self, terminal_reward: float = 0.0) -> Dict[str, float]:
        if not self.trajectory:
            return {"updated": 0, "reason": "empty trajectory"}

        rewards = [float(t.reward) for t in self.trajectory]
        rewards[-1] += float(terminal_reward)

        returns = []
        running = 0.0
        for r in reversed(rewards):
            running = r + self.gamma * running
            returns.append(running)
        returns.reverse()

        states = torch.tensor([t.state for t in self.trajectory], dtype=torch.float32, device=self.device)
        actions = torch.tensor([t.action for t in self.trajectory], dtype=torch.long, device=self.device)
        masks = torch.tensor([t.mask for t in self.trajectory], dtype=torch.float32, device=self.device)
        returns_t = torch.tensor(returns, dtype=torch.float32, device=self.device)

        # 标准化 return，减少训练抖动。
        norm_returns = returns_t
        if returns_t.numel() > 1:
            norm_returns = (returns_t - returns_t.mean()) / (returns_t.std(unbiased=False) + 1e-6)

        self.model.train()
        logits, values = self.model(states)
        masked_logits = logits.masked_fill(masks <= 0.0, -1e9)
        dist = Categorical(logits=masked_logits)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy().mean()

        advantages = norm_returns - values.detach()
        policy_loss = -(log_probs * advantages).mean()
        value_loss = F.mse_loss(values, norm_returns)
        loss = policy_loss + self.value_coef * value_loss - self.entropy_coef * entropy

        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
        self.optimizer.step()

        self.update_count += 1
        summary = {
            "updated": 1,
            "update_count": self.update_count,
            "steps": len(self.trajectory),
            "terminal_reward": float(terminal_reward),
            "reward_sum": float(sum(rewards)),
            "return_mean": float(returns_t.mean().item()),
            "loss": float(loss.item()),
            "policy_loss": float(policy_loss.item()),
            "value_loss": float(value_loss.item()),
            "entropy": float(entropy.item()),
        }
        self.save()
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        self.clear_episode()
        return summary
