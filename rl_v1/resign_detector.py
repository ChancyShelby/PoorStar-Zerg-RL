# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ResignDecision:
    should_resign: bool
    reason: str = ""


class ResignDetector:
    """训练用提前认输检测器。

    目标不是像人类一样判断所有胜负，而是识别“已经没有训练价值的垃圾时间”。
    满足 hopeless 条件并持续一小段时间后，bot 会发送 gg 并 leave game，episode 记为 ResignedDefeat。
    """

    def __init__(self, bot, persist_seconds: float = 18.0, min_time: float = 420.0):
        self.bot = bot
        self.persist_seconds = float(persist_seconds)
        self.min_time = float(min_time)
        self.first_hopeless_time: Optional[float] = None
        self.last_reason: str = ""

    def _enemy_base_estimate(self) -> int:
        try:
            scout = getattr(self.bot, "scout", None)
            intel = getattr(scout, "intel", None)
            count = 1
            if intel is not None:
                if getattr(intel, "enemy_natural_seen", None) is True:
                    count += 1
                if getattr(intel, "enemy_third_seen", None) is True:
                    count += 1
            try:
                th_names = {"HATCHERY", "LAIR", "HIVE", "NEXUS", "COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS"}
                visible = self.bot.enemy_structures.filter(lambda s: getattr(getattr(s, "type_id", None), "name", "") in th_names)
                count = max(count, visible.amount)
            except Exception:
                pass
            return int(count)
        except Exception:
            return 1

    def _production_structures_left(self) -> int:
        try:
            prod_names = {
                "HATCHERY", "LAIR", "HIVE", "SPAWNINGPOOL", "ROACHWARREN", "HYDRALISKDEN",
                "BANELINGNEST", "SPIRE", "INFESTATIONPIT", "LURKERDENMP", "ULTRALISKCAVERN",
            }
            return int(self.bot.structures.filter(lambda s: getattr(getattr(s, "type_id", None), "name", "") in prod_names).amount)
        except Exception:
            return 0

    def check(self) -> ResignDecision:
        bot = self.bot
        try:
            t = float(getattr(bot, "time", 0.0))
            workers = float(getattr(bot, "workers", []).amount if getattr(bot, "workers", None) is not None else 0)
            army = float(getattr(bot, "supply_army", 0.0) or 0.0)
            supply = float(getattr(bot, "supply_used", 0.0) or 0.0)
            bases = int(getattr(bot, "townhalls", []).ready.amount if getattr(bot, "townhalls", None) is not None else 0)
            pending_bases = int(getattr(bot, "already_pending", lambda *_: 0)(__import__("sc2.ids.unit_typeid", fromlist=["UnitTypeId"]).UnitTypeId.HATCHERY))
        except Exception:
            return ResignDecision(False, "state read failed")

        # 开局保护：opening/RL 切换附近绝对不允许因为经济读数波动而认输。
        # 但如果 4 分钟后基地和生产建筑都没了，允许硬死亡提前结束垃圾时间。
        if t < 240:
            self.first_hopeless_time = None
            return ResignDecision(False, "too early")

        enemy_bases = self._enemy_base_estimate()
        prod_left = self._production_structures_left()
        reason = ""

        hard_dead = bases <= 0 and prod_left <= 1
        if hard_dead:
            reason = f"no townhall and almost no production left: bases={bases}, prod={prod_left}"
        elif t < self.min_time:
            self.first_hopeless_time = None
            self.last_reason = ""
            return ResignDecision(False, f"before resign_min_time={self.min_time:.0f}s")
        elif t >= 360 and bases <= 1 and workers < 16 and army < 12 and enemy_bases >= 2:
            reason = f"6min hopeless: bases={bases}, workers={workers:.0f}, army={army:.0f}, enemy_bases={enemy_bases}"
        elif t >= 480 and bases <= 2 and workers < 26 and army < 20 and supply < 75 and enemy_bases >= 2:
            reason = f"8min hopeless: bases={bases}, workers={workers:.0f}, army={army:.0f}, supply={supply:.0f}, enemy_bases={enemy_bases}"
        elif t >= 600 and bases <= 2 and workers < 32 and army < 28 and supply < 95 and enemy_bases >= 3:
            reason = f"10min hopeless: bases={bases}, workers={workers:.0f}, army={army:.0f}, supply={supply:.0f}, enemy_bases={enemy_bases}"
        elif t >= 720 and workers < 25 and army < 25 and supply < 90:
            reason = f"12min dead economy/army: workers={workers:.0f}, army={army:.0f}, supply={supply:.0f}"

        if not reason:
            self.first_hopeless_time = None
            self.last_reason = ""
            return ResignDecision(False, "not hopeless")

        now = t
        if self.first_hopeless_time is None:
            self.first_hopeless_time = now
            self.last_reason = reason
            return ResignDecision(False, f"hopeless candidate started: {reason}")

        if now - self.first_hopeless_time >= self.persist_seconds:
            return ResignDecision(True, f"{reason}; persisted {now - self.first_hopeless_time:.1f}s")

        self.last_reason = reason
        return ResignDecision(False, f"hopeless candidate persisting: {reason}")
