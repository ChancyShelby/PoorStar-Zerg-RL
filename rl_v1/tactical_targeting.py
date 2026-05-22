# -*- coding: utf-8 -*-
from __future__ import annotations

"""
TacticalTargetingManager v3.5

This layer sits above CombatCoordinator and below the macro/RL decision loop.
It does NOT try to micro individual casters.  Its job is to stop the bot from
repeatedly smashing the same ramp/main-base angle when a weaker expansion or
side target is available.

Core jobs:
- AttackTargetManager: prefer exposed outer bases / valuable structures instead of
  always walking into the enemy main.
- StallDetector: detect a stuck frontal push and rotate to a different target.
- HighGroundVisionController: send one air/scout unit ahead when the army is trying
  to attack a higher terrain target.

All army/scout commands go through CombatCoordinator when attached.
"""

from dataclasses import dataclass
from math import hypot
from typing import Optional, Iterable

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from rl_v1.combat_coordinator import CommandPriority, get_combat_coordinator


@dataclass
class TacticalResult:
    ok: bool = False
    issued_attack: int = 0
    issued_vision: int = 0
    target: Optional[Point2] = None
    mode: str = "idle"
    reason: str = ""


class TacticalTargetingManager:
    TOWNHALL_NAMES = {
        "HATCHERY", "LAIR", "HIVE",
        "NEXUS",
        "COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS",
    }
    TECH_STRUCTURE_NAMES = {
        "SPAWNINGPOOL", "ROACHWARREN", "BANELINGNEST", "HYDRALISKDEN", "LURKERDENMP",
        "SPIRE", "GREATERSPIRE", "INFESTATIONPIT", "ULTRALISKCAVERN", "EVOLUTIONCHAMBER",
        "TWILIGHTCOUNCIL", "ROBOTICSFACILITY", "STARGATE", "TEMPLARARCHIVE", "DARKSHRINE",
        "FLEETBEACON", "ROBOTICSBAY", "FORGE", "CYBERNETICSCORE",
        "BARRACKS", "FACTORY", "STARPORT", "FUSIONCORE", "GHOSTACADEMY", "ENGINEERINGBAY", "ARMORY",
    }
    STATIC_DEFENSE_NAMES = {
        "SPINECRAWLER", "SPORECRAWLER", "PHOTONCANNON", "SHIELDBATTERY", "BUNKER", "MISSILETURRET", "PLANETARYFORTRESS"
    }
    COMBAT_NAMES = {
        "ZERGLING", "BANELING", "ROACH", "RAVAGER", "HYDRALISK", "ULTRALISK",
        "MUTALISK", "CORRUPTOR", "BROODLORD", "SWARMHOST", "SWARMHOSTMP",
        "INFESTOR", "VIPER", "LURKER", "LURKERMP", "LURKERBURROWED", "LURKERMPBURROWED",
    }
    MAIN_ARMY_NAMES = {
        "ZERGLING", "BANELING", "ROACH", "RAVAGER", "HYDRALISK", "ULTRALISK",
        "BROODLORD", "LURKER", "LURKERMP", "LURKERBURROWED", "LURKERMPBURROWED",
    }
    VISION_PROVIDER_NAMES = [
        "OVERSEER", "OVERSEERSIEGEMODE", "OVERLORD", "OVERLORDTRANSPORT",
        "MUTALISK", "CORRUPTOR", "BROODLORD",
    ]

    def __init__(self, bot, interval: float = 3.0):
        self.bot = bot
        self.interval = float(interval)
        self.last_step_time = -999.0
        self.last_attack_issue_time = -999.0
        self.last_vision_issue_time = -999.0
        self.last_log_time = -999.0
        self.current_target: Optional[Point2] = None
        self.current_target_key: Optional[tuple[int, int]] = None
        self.current_target_started = -999.0
        self.last_army_center: Optional[Point2] = None
        self.last_distance_to_target: Optional[float] = None
        self.last_progress_time = -999.0
        self.target_blacklist_until: dict[tuple[int, int], float] = {}
        self.force_rotate_until = -999.0

    # ----------------------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------------------
    def _now(self) -> float:
        try:
            return float(getattr(self.bot, "time", 0.0) or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _name(unit) -> str:
        try:
            return str(unit.type_id.name).upper()
        except Exception:
            return ""

    @staticmethod
    def _u(name: str):
        try:
            return UnitTypeId.__members__.get(str(name).upper())
        except Exception:
            return None

    @staticmethod
    def _point_key(p: Point2, cell: float = 6.0) -> tuple[int, int]:
        return (int(round(float(p.x) / cell)), int(round(float(p.y) / cell)))

    def _coord(self):
        return get_combat_coordinator(self.bot)

    def _terrain_height(self, p: Point2) -> float:
        try:
            return float(self.bot.get_terrain_z_height(p))
        except Exception:
            try:
                # Some python-sc2 builds expose terrain height through game_info.
                return float(self.bot.game_info.terrain_height[p])
            except Exception:
                return 0.0

    def _is_visible(self, p: Point2) -> bool:
        try:
            fn = getattr(self.bot, "is_visible", None)
            if callable(fn):
                return bool(fn(p))
        except Exception:
            pass
        try:
            # Fail open for compatibility; placement manager handles strict visibility.
            return True
        except Exception:
            return True

    def _towards(self, start: Point2, target: Point2, distance: float) -> Point2:
        try:
            return start.towards(target, distance)
        except Exception:
            dx = float(target.x - start.x)
            dy = float(target.y - start.y)
            d = hypot(dx, dy) or 1.0
            return Point2((float(start.x + dx / d * distance), float(start.y + dy / d * distance)))

    def _combat_units(self, main_only: bool = False):
        names = self.MAIN_ARMY_NAMES if main_only else self.COMBAT_NAMES
        ids = [self._u(n) for n in names]
        ids = [x for x in ids if x is not None]
        try:
            return self.bot.units.ready.filter(lambda u: u.type_id in set(ids))
        except Exception:
            try:
                return self.bot.units.ready.filter(lambda u: self._name(u) in names)
            except Exception:
                return self.bot.units.filter(lambda u: False)

    def _army_center(self) -> Optional[Point2]:
        try:
            army = self._combat_units(main_only=True)
            if army.exists:
                return army.center
        except Exception:
            pass
        try:
            army = self._combat_units(main_only=False)
            if army.exists:
                return army.center
        except Exception:
            pass
        try:
            if self.bot.townhalls.ready.exists:
                return self.bot.townhalls.ready.closest_to(self.bot.enemy_start_locations[0]).position
        except Exception:
            pass
        return None

    def _enemy_main(self) -> Point2:
        try:
            if self.bot.enemy_start_locations:
                return self.bot.enemy_start_locations[0]
        except Exception:
            pass
        try:
            return self.bot.game_info.map_center
        except Exception:
            return Point2((0, 0))

    def _visible_enemy_static_near(self, p: Point2, radius: float = 13.0) -> int:
        try:
            structs = self.bot.enemy_structures.filter(lambda s: self._name(s) in self.STATIC_DEFENSE_NAMES and s.distance_to(p) <= radius)
            return int(structs.amount)
        except Exception:
            return 0

    def _visible_enemy_army_near(self, p: Point2, radius: float = 13.0) -> int:
        try:
            enemies = self.bot.enemy_units.filter(lambda u: not getattr(u, "is_structure", False) and u.distance_to(p) <= radius)
            return int(enemies.amount)
        except Exception:
            return 0

    # ----------------------------------------------------------------------------------
    # Attack target selection
    # ----------------------------------------------------------------------------------
    def _candidate_enemy_structures(self):
        try:
            structs = self.bot.enemy_structures
            if structs is not None and structs.exists:
                return list(structs)
        except Exception:
            pass
        return []

    def _score_target(self, s, army_center: Optional[Point2], force_rotate: bool = False) -> float:
        name = self._name(s)
        p = s.position
        enemy_main = self._enemy_main()
        now = self._now()
        key = self._point_key(p)
        if self.target_blacklist_until.get(key, -999.0) > now:
            return -10_000.0

        # Start from type value.
        score = 0.0
        if name in self.TOWNHALL_NAMES:
            score += 900.0
            # Farther from enemy main usually means outer expansion.  This is exactly the
            # "do not keep ramming main; punish bases" behavior.
            score += 7.0 * p.distance_to(enemy_main)
        elif name in self.TECH_STRUCTURE_NAMES:
            score += 420.0
            score += 2.0 * p.distance_to(enemy_main)
        elif name in self.STATIC_DEFENSE_NAMES:
            # Do not choose cannons/spores/bunkers as a strategic target unless nothing else exists.
            score += 80.0
        else:
            score += 180.0

        if army_center is not None:
            score -= 1.2 * p.distance_to(army_center)
            # If this target is higher than the army, treat it as harder unless we are explicitly
            # doing a siege-break.  This pushes the target selector toward side bases when stuck.
            h_army = self._terrain_height(army_center)
            h_target = self._terrain_height(p)
            if h_target > h_army + 0.75:
                score -= 220.0
                if force_rotate:
                    score -= 260.0

        defenders = self._visible_enemy_army_near(p, 12.0)
        static = self._visible_enemy_static_near(p, 12.0)
        score -= defenders * 28.0
        score -= static * 85.0

        # If stalled, strongly prefer townhalls / side targets over main tech piles.
        if force_rotate:
            if name in self.TOWNHALL_NAMES:
                score += 450.0
            if p.distance_to(enemy_main) > 22.0:
                score += 240.0
        return score

    def get_attack_target(self, force_rotate: bool = False) -> Optional[Point2]:
        army_center = self._army_center()
        structs = self._candidate_enemy_structures()
        if structs:
            best = max(structs, key=lambda s: self._score_target(s, army_center, force_rotate=force_rotate))
            if self._score_target(best, army_center, force_rotate=force_rotate) > -1000.0:
                return best.position

        # If no visible structure: ask map hunt manager to sweep likely bases.
        hunt = getattr(self.bot, "map_hunt_manager", None)
        if hunt is not None:
            try:
                target = hunt.next_target()
                if target is not None:
                    return target
            except Exception:
                pass
        try:
            return self.bot.enemy_start_locations[0]
        except Exception:
            try:
                return self.bot.game_info.map_center
            except Exception:
                return None

    # ----------------------------------------------------------------------------------
    # Stall detector / high ground vision
    # ----------------------------------------------------------------------------------
    def _update_stall_state(self, target: Optional[Point2], army_center: Optional[Point2]) -> tuple[bool, str]:
        now = self._now()
        if target is None or army_center is None:
            return False, "no target/army center"
        key = self._point_key(target)
        dist = army_center.distance_to(target)

        if key != self.current_target_key:
            self.current_target = target
            self.current_target_key = key
            self.current_target_started = now
            self.last_distance_to_target = dist
            self.last_progress_time = now
            self.last_army_center = army_center
            return False, "new target"

        old_dist = self.last_distance_to_target
        if old_dist is None or dist < old_dist - 2.0:
            self.last_distance_to_target = dist
            self.last_progress_time = now
            self.last_army_center = army_center
            return False, "progressing"

        # If the army sits in roughly the same place for long enough while close to the target,
        # assume ramp/building/siege congestion and rotate.
        moved = 999.0
        try:
            if self.last_army_center is not None:
                moved = army_center.distance_to(self.last_army_center)
        except Exception:
            pass
        if now - self.last_progress_time >= 28.0 and dist <= 34.0 and moved <= 7.5:
            self.target_blacklist_until[key] = now + 55.0
            self.force_rotate_until = now + 35.0
            self.last_progress_time = now
            return True, f"stalled: no approach progress for {now - self.current_target_started:.0f}s, dist={dist:.1f}, moved={moved:.1f}"

        self.last_army_center = army_center
        return False, "not stalled"

    def _needs_highground_vision(self, target: Optional[Point2], army_center: Optional[Point2]) -> bool:
        if target is None or army_center is None:
            return False
        try:
            if self._terrain_height(target) > self._terrain_height(army_center) + 0.75 and army_center.distance_to(target) < 40.0:
                return True
        except Exception:
            pass
        try:
            if not self._is_visible(target) and army_center.distance_to(target) < 35.0:
                return True
        except Exception:
            pass
        return False

    def _vision_providers(self):
        ids = [self._u(n) for n in self.VISION_PROVIDER_NAMES]
        ids = [x for x in ids if x is not None]
        try:
            units = self.bot.units.ready.filter(lambda u: u.type_id in set(ids))
        except Exception:
            try:
                units = self.bot.units.ready.filter(lambda u: self._name(u) in set(self.VISION_PROVIDER_NAMES))
            except Exception:
                return []
        try:
            # Do not suicide badly wounded air units for vision.
            units = units.filter(lambda u: getattr(u, "health_percentage", 1.0) >= 0.45)
        except Exception:
            pass
        return list(units)

    def _issue_move(self, unit, target, owner: str, priority: CommandPriority, duration: float, reason: str) -> bool:
        coord = self._coord()
        if coord is not None:
            return bool(coord.issue_move(unit, target, owner=owner, priority=priority, duration=duration, reason=reason))
        try:
            if int(unit.tag) in getattr(self.bot, "unit_tags_received_action", set()):
                return False
            unit.move(target)
            return True
        except Exception:
            return False

    def _issue_attack(self, unit, target, owner: str, priority: CommandPriority, duration: float, reason: str) -> bool:
        coord = self._coord()
        if coord is not None:
            return bool(coord.issue_attack(unit, target, owner=owner, priority=priority, duration=duration, reason=reason))
        try:
            if int(unit.tag) in getattr(self.bot, "unit_tags_received_action", set()):
                return False
            unit.attack(target)
            return True
        except Exception:
            return False

    def _send_highground_vision(self, target: Point2, army_center: Point2) -> int:
        now = self._now()
        if now - self.last_vision_issue_time < 6.0:
            return 0
        providers = self._vision_providers()
        if not providers:
            return 0
        provider = min(providers, key=lambda u: u.distance_to(target))
        dist = army_center.distance_to(target)
        # Put the scout ahead of the ground army, but do not intentionally fly to the very back
        # of the enemy base.  The goal is ramp/high-ground sight, not suicide scouting.
        step = max(7.0, min(18.0, dist - 4.0)) if dist > 10.0 else dist
        spot = self._towards(army_center, target, step)
        ok = self._issue_move(
            provider,
            spot,
            owner="HighGroundVisionController",
            priority=CommandPriority.HARASS,
            duration=6.0,
            reason="provide high-ground/ramp vision before army push",
        )
        if ok:
            self.last_vision_issue_time = now
            return 1
        return 0

    def _issue_army_attack(self, target: Point2, reason: str) -> int:
        now = self._now()
        if now - self.last_attack_issue_time < 6.0:
            return 0
        army = self._combat_units(main_only=True)
        try:
            if not army.exists or army.amount < 12:
                return 0
        except Exception:
            return 0
        issued = 0
        # cap prevents late-game command spam / client stalls
        for unit in list(army)[:110]:
            if self._issue_attack(
                unit,
                target,
                owner="TacticalAttackTargetManager",
                priority=CommandPriority.ARMY_ATTACK,
                duration=2.2,
                reason=reason,
            ):
                issued += 1
        if issued > 0:
            self.last_attack_issue_time = now
        return issued

    # ----------------------------------------------------------------------------------
    # Public step
    # ----------------------------------------------------------------------------------
    async def step(self, iteration: int = 0) -> TacticalResult:
        now = self._now()
        if now - self.last_step_time < self.interval:
            return TacticalResult(False, reason="cooldown")
        self.last_step_time = now

        try:
            supply = int(getattr(self.bot, "supply_used", 0) or 0)
            army_supply = int(getattr(self.bot, "supply_army", 0) or 0)
            minerals = int(getattr(self.bot, "minerals", 0) or 0)
        except Exception:
            supply, army_supply, minerals = 0, 0, 0

        # Do not disturb early/mid game unless army is already large.
        if now < 520.0 and supply < 160 and army_supply < 80:
            return TacticalResult(False, reason="not tactical phase yet")

        army_center = self._army_center()
        force_rotate = now < self.force_rotate_until
        target = self.get_attack_target(force_rotate=force_rotate)
        if target is None:
            return TacticalResult(False, reason="no tactical target")

        stalled, stall_reason = self._update_stall_state(target, army_center)
        if stalled:
            target = self.get_attack_target(force_rotate=True) or target

        vision = 0
        if self._needs_highground_vision(target, army_center):
            vision = self._send_highground_vision(target, army_center)

        attack_due = stalled or force_rotate or supply >= 188 or minerals >= 5500
        issued = 0
        reason = ""
        if attack_due:
            reason = ("rotate/punish expansion; " if (stalled or force_rotate) else "late tactical target; ") + stall_reason
            issued = self._issue_army_attack(target, reason=reason)

        if (issued or vision) and now - self.last_log_time >= 8.0:
            self.last_log_time = now
            try:
                print(f"[{now:06.1f}] TACTICAL mode={'rotate' if (stalled or force_rotate) else 'pressure'} target=({target.x:.1f},{target.y:.1f}) attack={issued} vision={vision} reason={reason or stall_reason}")
            except Exception:
                pass

        return TacticalResult(
            ok=bool(issued or vision),
            issued_attack=issued,
            issued_vision=vision,
            target=target,
            mode="rotate" if (stalled or force_rotate) else "pressure",
            reason=reason or stall_reason,
        )
