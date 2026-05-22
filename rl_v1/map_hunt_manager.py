# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sc2.position import Point2


@dataclass
class HuntSummary:
    ok: bool = False
    target: Optional[Point2] = None
    reason: str = ""


class MapHuntManager:
    """Search remaining hidden enemy bases after visible bases are destroyed.

    Problem fixed: when enemy main/natural are dead but the AI has a hidden base,
    the ordinary attack target falls back to enemy_start_locations[0], so the army
    waits at the dead main.  This manager cycles expansion locations and sends the
    army around the map when no enemy structure is visible for a while.
    """

    def __init__(self, bot, interval: float = 18.0):
        self.bot = bot
        self.interval = float(interval)
        self.last_hunt_time = -999.0
        self.last_visible_enemy_structure_time = -999.0
        self.index = 0
        self.cached_targets: List[Point2] = []

    def _enemy_structures_visible(self) -> bool:
        try:
            return bool(getattr(self.bot, "enemy_structures", None) is not None and self.bot.enemy_structures.exists)
        except Exception:
            return False

    def _own_base_near(self, p: Point2) -> bool:
        try:
            return self.bot.townhalls.exists and self.bot.townhalls.closer_than(12.0, p).exists
        except Exception:
            return False

    def _build_targets(self) -> List[Point2]:
        targets: List[Point2] = []
        try:
            enemy_start = self.bot.enemy_start_locations[0] if self.bot.enemy_start_locations else self.bot.game_info.map_center
        except Exception:
            enemy_start = self.bot.game_info.map_center
        try:
            expansions = list(getattr(self.bot, "expansion_locations_list", []) or [])
        except Exception:
            expansions = []
        # Search enemy-side expansions first, then the rest.  Exclude our own active bases.
        expansions = [p for p in expansions if not self._own_base_near(p)]
        expansions.sort(key=lambda p: p.distance_to(enemy_start))
        targets.extend(expansions)

        # Add map corners / center as last resort.  Use playable area if present.
        try:
            pa = self.bot.game_info.playable_area
            corners = [
                Point2((pa.x + 6, pa.y + 6)),
                Point2((pa.x + pa.width - 6, pa.y + 6)),
                Point2((pa.x + 6, pa.y + pa.height - 6)),
                Point2((pa.x + pa.width - 6, pa.y + pa.height - 6)),
                self.bot.game_info.map_center,
            ]
            targets.extend(corners)
        except Exception:
            pass

        # Deduplicate coarse coordinates.
        out: List[Point2] = []
        seen = set()
        for p in targets:
            key = (round(float(p.x), 1), round(float(p.y), 1))
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def next_target(self) -> Point2:
        if not self.cached_targets:
            self.cached_targets = self._build_targets()
        if not self.cached_targets:
            return self.bot.game_info.map_center
        target = self.cached_targets[self.index % len(self.cached_targets)]
        self.index += 1
        return target

    async def step(self, iteration: int) -> Optional[HuntSummary]:
        now = float(getattr(self.bot, "time", 0.0) or 0.0)
        if self._enemy_structures_visible():
            self.last_visible_enemy_structure_time = now
            return None

        # Do not hunt early.  Early lack of enemy structures just means we have not scouted yet.
        try:
            army_supply = float(getattr(self.bot, "supply_army", 0.0) or 0.0)
            supply_used = float(getattr(self.bot, "supply_used", 0.0) or 0.0)
        except Exception:
            army_supply, supply_used = 0.0, 0.0
        if now < 360 and supply_used < 150:
            return None
        if army_supply < 24 and supply_used < 165:
            return None
        if now - self.last_hunt_time < self.interval:
            return None
        # Give the normal combat manager some time after the last visible building disappears.
        if self.last_visible_enemy_structure_time > 0 and now - self.last_visible_enemy_structure_time < 8.0:
            return None

        executor = getattr(self.bot, "executor", None)
        if executor is None:
            return None
        target = self.next_target()
        self.last_hunt_time = now
        try:
            res = await executor.attack_move(
                action="HUNT_REMAINING_BASES",
                target=target,
                min_army_units=8,
                reason="no visible enemy structures; cycling expansion locations to find hidden base",
            )
        except Exception as exc:
            return HuntSummary(False, target, f"hunt exception {type(exc).__name__}: {exc}")
        if res is not None and res.ok:
            try:
                self.bot._record_success("ATTACK_MOVE")
            except Exception:
                pass
            return HuntSummary(True, target, res.reason)
        return HuntSummary(False, target, getattr(res, "reason", "hunt failed"))
