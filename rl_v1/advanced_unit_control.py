# -*- coding: utf-8 -*-
from __future__ import annotations

"""
AdvancedUnitControl v3.4

Purpose:
- This is still NOT the final micro-RL layer.
- It is a deterministic high-value-unit execution layer that sits under CombatCoordinator.
- It makes special units actively create spell conditions instead of only casting when everything
  happens to be perfect.

Main controllers in this file:
- ViperController: actively moves to friendly structures and consumes, then casts spell support.
- InfestorController: keeps backline, fungal/neural/shroud.
- RavagerBileController: casts corrosive bile on clusters/high-value targets.
- LurkerController: burrow/unburrow/follow army.
- MutaliskHarassController: preserve mutas, pick workers/isolated targets, retreat from anti-air.
- CorruptorController: fight air first, then optional caustic spray on exposed structures.
- BanelingController: simple anti-light/worker cluster detonation logic.

Design rule:
Every command must go through CombatCoordinator if available.  That keeps all special-unit
controllers compatible with ArmyWave/Retreat/BaseDefense ownership arbitration.
"""

from dataclasses import dataclass, field
from math import hypot
from typing import Iterable, Optional, Sequence

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2

from rl_v1.combat_coordinator import CommandPriority, get_combat_coordinator


@dataclass
class AdvancedControlSummary:
    actions: int = 0
    reason: str = ""
    counts: dict[str, int] = field(default_factory=dict)


class AdvancedUnitControl:
    """High-value Zerg unit controller layer.

    It intentionally uses simple, auditable heuristics first.  Later, individual target scorers
    or micro-RL policies can replace specific decision points while keeping the same ownership
    and command interface.
    """

    HIGH_VALUE_GROUND = {
        "SIEGETANK", "SIEGETANKSIEGED", "THOR", "COLOSSUS", "DISRUPTOR", "IMMORTAL",
        "HIGHTEMPLAR", "ARCHON", "GHOST", "RAVEN", "INFESTOR", "VIPER", "LURKERMP",
        "LURKER", "LURKERMPBURROWED", "LURKERBURROWED", "ULTRALISK", "CYCLONE",
        "WIDOWMINE", "WIDOWMINEBURROWED",
    }
    HIGH_VALUE_AIR = {
        "BATTLECRUISER", "CARRIER", "TEMPEST", "MOTHERSHIP", "VOIDRAY", "PHOENIX",
        "VIKINGFIGHTER", "LIBERATOR", "LIBERATORAG", "CORRUPTOR", "BROODLORD",
        "RAVEN", "BANSHEE", "ORACLE", "MUTALISK",
    }
    ANTI_AIR_THREATS = {
        "MARINE", "MARAUDER", "QUEEN", "HYDRALISK", "STALKER", "ARCHON", "PHOENIX",
        "VOIDRAY", "VIKINGFIGHTER", "VIKINGASSAULT", "CORRUPTOR", "THOR", "CYCLONE",
        "MISSILETURRET", "SPORECRAWLER", "PHOTONCANNON", "BATTLECRUISER", "CARRIER",
        "TEMPEST", "LIBERATOR", "LIBERATORAG",
    }
    LIGHT_BIO_OR_WORKER = {
        "SCV", "DRONE", "PROBE", "MULE", "MARINE", "MARAUDER", "REAPER", "HELLION",
        "ZEALOT", "ADEPT", "SENTRY", "HIGHTEMPLAR", "DARKTEMPLAR", "ZERGLING",
        "BANELING", "HYDRALISK",
    }
    CONSUME_BLACKLIST = {
        "HATCHERY", "LAIR", "HIVE", "SPAWNINGPOOL", "ROACHWARREN", "BANELINGNEST",
        "HYDRALISKDEN", "SPIRE", "GREATERSPIRE", "INFESTATIONPIT", "ULTRALISKCAVERN",
        "LURKERDENMP", "LURKERDEN", "NYDUSNETWORK", "NYDUSCANAL",
    }

    def __init__(self, bot, interval: float = 1.0, max_units_per_step: int = 18):
        self.bot = bot
        self.interval = float(interval)
        self.max_units_per_step = int(max_units_per_step)
        self.last_step_time = -999.0
        self.cast_cooldown_until: dict[tuple[int, str], float] = {}
        self.recent_point_cooldown: dict[tuple[str, int, int], float] = {}
        self.last_muta_side_switch = -999.0
        self.muta_side = 1

    # -------------------------------------------------------------------------------------
    # Generic helpers
    # -------------------------------------------------------------------------------------
    def _coord(self):
        return get_combat_coordinator(self.bot)

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
            try:
                return str(unit.type_id).split(".")[-1].upper()
            except Exception:
                return ""

    @staticmethod
    def _u(name: str):
        try:
            return UnitTypeId.__members__.get(str(name).upper())
        except Exception:
            return None

    @staticmethod
    def _ability(name: str):
        try:
            return AbilityId.__members__.get(str(name).upper())
        except Exception:
            return None

    def _cooldown_active(self, tag: int, key: str) -> bool:
        return self.cast_cooldown_until.get((int(tag), str(key)), -999.0) > self._now()

    def _set_cooldown(self, tag: int, key: str, seconds: float = 3.0) -> None:
        self.cast_cooldown_until[(int(tag), str(key))] = self._now() + float(seconds)

    def _point_key(self, p: Point2, grid: float = 2.5) -> tuple[int, int]:
        try:
            return (int(round(float(p.x) / grid)), int(round(float(p.y) / grid)))
        except Exception:
            return (0, 0)

    def _point_recent(self, key: str, p: Point2, seconds: float) -> bool:
        return self.recent_point_cooldown.get((str(key), *self._point_key(p)), -999.0) > self._now()

    def _mark_point(self, key: str, p: Point2, seconds: float) -> None:
        self.recent_point_cooldown[(str(key), *self._point_key(p))] = self._now() + float(seconds)

    async def _available(self, unit) -> Sequence:
        try:
            return await self.bot.get_available_abilities(unit)
        except Exception:
            return []

    async def _cast(
        self,
        unit,
        ability_names: Iterable[str],
        target=None,
        key: str = "spell",
        cooldown: float = 3.0,
        owner: Optional[str] = None,
        priority: CommandPriority | int = CommandPriority.SPELLCAST,
        duration: Optional[float] = None,
    ) -> bool:
        try:
            if int(unit.tag) in getattr(self.bot, "unit_tags_received_action", set()):
                return False
        except Exception:
            pass
        if self._cooldown_active(unit.tag, key):
            return False

        abilities = await self._available(unit)
        for name in ability_names:
            ability = self._ability(name)
            if ability is None or ability not in abilities:
                continue
            coord = self._coord()
            if coord is not None:
                ok = coord.issue_ability(
                    unit,
                    ability,
                    target=target,
                    owner=owner or f"AdvancedUnitControl:{key}",
                    priority=priority,
                    duration=max(float(duration or cooldown), 1.2),
                    reason=f"advanced cast {key}",
                )
            else:
                try:
                    if target is None:
                        unit(ability)
                    else:
                        unit(ability, target)
                    ok = True
                except Exception:
                    ok = False
            if ok:
                self._set_cooldown(unit.tag, key, cooldown)
                return True
        return False

    def _issue_move(self, unit, target, *, owner: str, priority=CommandPriority.SPELLCAST, duration: float = 2.0, reason: str = "") -> bool:
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

    def _issue_attack(self, unit, target, *, owner: str, priority=CommandPriority.HARASS, duration: float = 1.8, reason: str = "") -> bool:
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

    def _enemy_units(self, include_structures: bool = False):
        try:
            enemies = self.bot.enemy_units
            if include_structures:
                return enemies | self.bot.enemy_structures
            return enemies.filter(lambda u: not u.is_structure)
        except Exception:
            try:
                return self.bot.enemy_units
            except Exception:
                return []

    @staticmethod
    def _center(units) -> Optional[Point2]:
        try:
            if not units.exists:
                return None
            return Point2((sum(u.position.x for u in units) / units.amount, sum(u.position.y for u in units) / units.amount))
        except Exception:
            return None

    def _army_center(self) -> Optional[Point2]:
        combat_names = {
            "ZERGLING", "BANELING", "ROACH", "RAVAGER", "HYDRALISK", "ULTRALISK",
            "LURKERMP", "LURKER", "BROODLORD", "CORRUPTOR", "MUTALISK",
        }
        try:
            units = self.bot.units.ready.filter(lambda u: self._name(u) in combat_names)
            if units.exists:
                return self._center(units)
        except Exception:
            pass
        try:
            if self.bot.townhalls.ready.exists:
                return self.bot.townhalls.ready.random.position
        except Exception:
            pass
        return None

    def _home_position(self) -> Optional[Point2]:
        try:
            if self.bot.townhalls.ready.exists:
                return self.bot.townhalls.ready.closest_to(self.bot.start_location).position
        except Exception:
            pass
        try:
            return self.bot.start_location
        except Exception:
            return None

    def _towards(self, start: Point2, target: Point2, distance: float) -> Point2:
        try:
            dx = float(target.x - start.x)
            dy = float(target.y - start.y)
            d = hypot(dx, dy) or 1.0
            return Point2((float(start.x + dx / d * distance), float(start.y + dy / d * distance)))
        except Exception:
            return target

    def _away_from(self, start: Point2, threat: Point2, distance: float) -> Point2:
        try:
            dx = float(start.x - threat.x)
            dy = float(start.y - threat.y)
            d = hypot(dx, dy) or 1.0
            return Point2((float(start.x + dx / d * distance), float(start.y + dy / d * distance)))
        except Exception:
            home = self._home_position()
            return home or start

    def _safe_back_point(self, unit, threat_units=None, distance: float = 7.0) -> Point2:
        try:
            if threat_units is not None and getattr(threat_units, "exists", False):
                center = self._center(threat_units)
                if center is not None:
                    return self._away_from(unit.position, center, distance)
        except Exception:
            pass
        home = self._home_position()
        if home is not None:
            return self._towards(unit.position, home, min(distance, unit.distance_to(home)))
        return unit.position

    @staticmethod
    def _score_enemy_value(enemy) -> float:
        try:
            hp = float(getattr(enemy, "health", 0.0) or 0.0) + float(getattr(enemy, "shield", 0.0) or 0.0)
            r = float(getattr(enemy, "radius", 0.5) or 0.5)
            name = str(enemy.type_id.name).upper()
            bonus = 180.0 if name in AdvancedUnitControl.HIGH_VALUE_GROUND or name in AdvancedUnitControl.HIGH_VALUE_AIR else 0.0
            if getattr(enemy, "is_structure", False):
                bonus += 60.0
            return hp + 70.0 * r + bonus
        except Exception:
            return 1.0

    # -------------------------------------------------------------------------------------
    # Viper
    # -------------------------------------------------------------------------------------
    def _consume_structures(self, viper, max_range: float = 26.0):
        bot = self.bot
        try:
            structs = bot.structures.ready.filter(
                lambda s: s.distance_to(viper) <= max_range
                and s.health_percentage > 0.42
                and self._name(s) not in self.CONSUME_BLACKLIST
            )
            if structs.exists:
                # Prefer cheap / expendable structures near the viper.  Evolution chambers, extractors,
                # spores/spines are acceptable; never force hatch/lair/hive consume.
                return sorted(list(structs), key=lambda s: (s.distance_to(viper), -float(getattr(s, "health", 0.0) or 0.0)))
        except Exception:
            pass
        return []

    async def _control_vipers(self) -> int:
        bot = self.bot
        try:
            vipers = bot.units(UnitTypeId.VIPER).ready
        except Exception:
            return 0
        if not vipers.exists:
            return 0

        enemies = self._enemy_units()
        count = 0
        for v in list(vipers)[: self.max_units_per_step]:
            energy = float(getattr(v, "energy", 0.0) or 0.0)
            try:
                close_threat = enemies.closer_than(6.5, v) if getattr(enemies, "exists", False) else enemies
            except Exception:
                close_threat = []

            # 0) Caster survival.  A dead viper is worse than no spell.
            try:
                if getattr(close_threat, "exists", False):
                    if self._issue_move(
                        v,
                        self._safe_back_point(v, close_threat, 8.0),
                        owner="ViperController:retreat",
                        priority=CommandPriority.EMERGENCY_RETREAT,
                        duration=1.2,
                        reason="viper too close to enemy; preserve caster",
                    ):
                        count += 1
                        continue
            except Exception:
                pass

            # 1) Active consume.  This is the important fix: do not wait for a structure to be
            # already in exact cast range.  Move the viper toward a consume target first.
            if energy < 150:
                structs = self._consume_structures(v, max_range=30.0)
                if structs:
                    target = structs[0]
                    dist = v.distance_to(target)
                    if dist <= 8.2:
                        if await self._cast(
                            v,
                            [
                                "VIPERCONSUMESTRUCTURE_VIPERCONSUME",
                                "EFFECT_VIPERCONSUME",
                                "EFFECT_CONSUME",
                                "CONSUMESTRUCTURE",
                            ],
                            target=target,
                            key="viper_consume",
                            cooldown=3.5,
                            owner="ViperController:consume",
                            duration=3.8,
                        ):
                            count += 1
                            continue
                    else:
                        approach = self._towards(v.position, target.position, min(6.0, max(2.0, dist - 6.5)))
                        if self._issue_move(
                            v,
                            approach,
                            owner="ViperController:consume_move",
                            priority=CommandPriority.SPELLCAST,
                            duration=2.2,
                            reason="move viper to friendly structure for consume",
                        ):
                            count += 1
                            continue

            if not getattr(enemies, "exists", False) or energy < 75:
                # Keep vipers behind army instead of idle drifting forward.
                army = self._army_center()
                if army is not None and v.distance_to(army) > 11.0:
                    if self._issue_move(v, army, owner="ViperController:follow_army", priority=CommandPriority.SPELLCAST, duration=1.5, reason="viper follow army backline"):
                        count += 1
                continue

            # 2) Parasitic bomb on air clumps / high value air.
            try:
                air = enemies.filter(lambda e: getattr(e, "is_flying", False) and e.distance_to(v) <= 10.5)
                if energy >= 125 and air.exists:
                    # Prefer a target with nearby friends to maximize splash.
                    def air_score(e):
                        try:
                            nearby = air.closer_than(3.2, e).amount
                        except Exception:
                            nearby = 1
                        return self._score_enemy_value(e) + 120.0 * nearby
                    target = max(list(air), key=air_score)
                    if await self._cast(v, ["EFFECT_PARASITICBOMB", "PARASITICBOMB_PARASITICBOMB"], target=target, key="viper_pb", cooldown=7.0, owner="ViperController:parasitic_bomb", duration=5.0):
                        count += 1
                        continue
            except Exception:
                pass

            # 3) Blinding cloud on siege / dense ranged ground.
            try:
                ground = enemies.filter(lambda e: not getattr(e, "is_flying", False) and e.distance_to(v) <= 10.5)
                siege = ground.filter(lambda e: self._name(e) in {"SIEGETANK", "SIEGETANKSIEGED", "COLOSSUS", "LURKERMPBURROWED", "LURKERBURROWED", "THOR", "IMMORTAL", "ARCHON"})
                cloud_candidates = siege if siege.exists else ground
                if energy >= 100 and cloud_candidates.amount >= (1 if siege.exists else 4):
                    center = self._center(cloud_candidates.closer_than(4.5, cloud_candidates.closest_to(v))) if cloud_candidates.exists else None
                    if center is None:
                        center = self._center(cloud_candidates)
                    if center is not None and not self._point_recent("viper_cloud", center, 3.5):
                        if await self._cast(v, ["EFFECT_BLINDINGCLOUD", "BLINDINGCLOUD_BLINDINGCLOUD"], target=center, key="viper_cloud", cooldown=6.0, owner="ViperController:blinding_cloud", duration=5.0):
                            self._mark_point("viper_cloud", center, 3.5)
                            count += 1
                            continue
            except Exception:
                pass

            # 4) Abduct high value units.
            try:
                abductable = enemies.filter(lambda e: not e.is_structure and e.distance_to(v) <= 9.5)
                if energy >= 75 and abductable.exists:
                    target = max(list(abductable), key=self._score_enemy_value)
                    if self._score_enemy_value(target) >= 170.0:
                        if await self._cast(v, ["EFFECT_ABDUCT", "ABDUCT_ABDUCT"], target=target, key="viper_abduct", cooldown=4.5, owner="ViperController:abduct", duration=4.0):
                            count += 1
                            continue
            except Exception:
                pass
        return count

    # -------------------------------------------------------------------------------------
    # Infestor
    # -------------------------------------------------------------------------------------
    async def _control_infestors(self) -> int:
        bot = self.bot
        try:
            infestors = bot.units(UnitTypeId.INFESTOR).ready
        except Exception:
            return 0
        if not infestors.exists:
            return 0

        enemies = self._enemy_units()
        if not getattr(enemies, "exists", False):
            return 0
        count = 0
        for inf in list(infestors)[: self.max_units_per_step]:
            energy = float(getattr(inf, "energy", 0.0) or 0.0)
            try:
                danger = enemies.closer_than(6.0, inf)
                if danger.exists:
                    if self._issue_move(inf, self._safe_back_point(inf, danger, 7.5), owner="InfestorController:retreat", priority=CommandPriority.EMERGENCY_RETREAT, duration=1.3, reason="infestor too close; preserve caster"):
                        count += 1
                        continue
            except Exception:
                pass
            if energy < 70:
                continue
            try:
                nearby = enemies.closer_than(10.0, inf)
                if not nearby.exists:
                    continue

                # Neural: only on high-value heavy targets, not random zealots/zerglings.
                if energy >= 100:
                    heavy = nearby.filter(lambda e: not e.is_structure and self._score_enemy_value(e) >= 230.0)
                    if heavy.exists:
                        target = max(list(heavy), key=self._score_enemy_value)
                        if await self._cast(inf, ["NEURALPARASITE_NEURALPARASITE", "EFFECT_NEURALPARASITE", "NEURALPARASITE"], target=target, key="inf_neural", cooldown=8.5, owner="InfestorController:neural", duration=6.0):
                            count += 1
                            continue

                # Fungal: use on dense mobile units, including air clumps if present.
                mobile = nearby.filter(lambda e: not e.is_structure)
                if energy >= 75 and mobile.amount >= 3:
                    center = self._center(mobile)
                    if center is not None and not self._point_recent("inf_fungal", center, 2.8):
                        if await self._cast(inf, ["FUNGALGROWTH_FUNGALGROWTH", "EFFECT_FUNGALGROWTH", "FUNGALGROWTH"], target=center, key="inf_fungal", cooldown=5.5, owner="InfestorController:fungal", duration=4.5):
                            self._mark_point("inf_fungal", center, 2.8)
                            count += 1
                            continue

                # Microbial shroud: only when enemy air is pressuring our hydra/corruptor clump.
                if energy >= 75:
                    air = nearby.filter(lambda e: getattr(e, "is_flying", False))
                    hydras = bot.units(UnitTypeId.HYDRALISK).ready.closer_than(8.5, inf)
                    if air.exists and hydras.amount >= 4:
                        center = self._center(hydras)
                        if center is not None and await self._cast(inf, ["EFFECT_MICROBIALSHROUD", "MICROBIALSHROUD_MICROBIALSHROUD"], target=center, key="inf_shroud", cooldown=9.0, owner="InfestorController:shroud", duration=6.0):
                            count += 1
                            continue
            except Exception:
                continue
        return count

    # -------------------------------------------------------------------------------------
    # Ravager bile
    # -------------------------------------------------------------------------------------
    async def _control_ravagers(self) -> int:
        bot = self.bot
        try:
            ravagers = bot.units(UnitTypeId.RAVAGER).ready
        except Exception:
            return 0
        if not ravagers.exists:
            return 0
        enemies = self._enemy_units(include_structures=True)
        if not getattr(enemies, "exists", False):
            return 0
        count = 0
        for r in list(ravagers)[: self.max_units_per_step]:
            try:
                in_range = enemies.filter(lambda e: e.distance_to(r) <= 9.2)
                if not in_range.exists:
                    continue
                # Prefer clumps, siege/high value, then structures.
                target_unit = max(list(in_range), key=lambda e: self._score_enemy_value(e) + 80.0 * in_range.closer_than(2.2, e).amount)
                target_point = target_unit.position
                if self._point_recent("ravager_bile", target_point, 2.4):
                    continue
                if await self._cast(
                    r,
                    ["EFFECT_CORROSIVEBILE", "CORROSIVEBILE_CORROSIVEBILE"],
                    target=target_point,
                    key="ravager_bile",
                    cooldown=6.5,
                    owner="RavagerBileController:bile",
                    priority=CommandPriority.SPELLCAST,
                    duration=3.2,
                ):
                    self._mark_point("ravager_bile", target_point, 2.4)
                    count += 1
            except Exception:
                continue
        return count

    # -------------------------------------------------------------------------------------
    # Lurker
    # -------------------------------------------------------------------------------------
    async def _control_lurkers(self) -> int:
        bot = self.bot
        count = 0
        lurker = getattr(UnitTypeId, "LURKERMP", None) or getattr(UnitTypeId, "LURKER", None)
        lurker_burrowed = getattr(UnitTypeId, "LURKERMPBURROWED", None) or getattr(UnitTypeId, "LURKERBURROWED", None)
        enemies = self._enemy_units()
        army_center = self._army_center()

        if lurker is not None:
            try:
                for u in list(bot.units(lurker).ready)[: self.max_units_per_step]:
                    nearby = enemies.closer_than(10.5, u) if getattr(enemies, "exists", False) else enemies
                    if getattr(nearby, "exists", False):
                        if await self._cast(u, ["BURROWDOWN_LURKER", "BURROWDOWN_LURKERMP", "BURROWDOWN"], key="lurker_burrow", cooldown=3.5, owner="LurkerController:burrow", duration=4.0):
                            count += 1
                            continue
                    if army_center is not None and u.distance_to(army_center) > 8.0:
                        if self._issue_move(u, army_center, owner="LurkerController:follow_army", priority=CommandPriority.SPELLCAST, duration=2.0, reason="unburrowed lurker follow army"):
                            count += 1
            except Exception:
                pass

        if lurker_burrowed is not None:
            try:
                for u in list(bot.units(lurker_burrowed).ready)[: self.max_units_per_step]:
                    nearby = enemies.closer_than(13.0, u) if getattr(enemies, "exists", False) else enemies
                    # If nothing nearby and army has moved away, unburrow to rejoin.
                    should_unburrow = not getattr(nearby, "exists", False)
                    if army_center is not None:
                        should_unburrow = should_unburrow and u.distance_to(army_center) > 10.5
                    if should_unburrow:
                        if await self._cast(u, ["BURROWUP_LURKER", "BURROWUP_LURKERMP", "BURROWUP"], key="lurker_unburrow", cooldown=7.0, owner="LurkerController:unburrow", duration=4.0):
                            count += 1
            except Exception:
                pass
        return count

    # -------------------------------------------------------------------------------------
    # Mutalisk harass
    # -------------------------------------------------------------------------------------
    def _anti_air_near(self, unit, radius: float = 8.5):
        try:
            enemies = self._enemy_units(include_structures=True)
            return enemies.filter(lambda e: self._name(e) in self.ANTI_AIR_THREATS and e.distance_to(unit) <= radius)
        except Exception:
            return []

    async def _control_mutalisks(self) -> int:
        bot = self.bot
        try:
            mutas = bot.units(UnitTypeId.MUTALISK).ready
        except Exception:
            return 0
        if not mutas.exists:
            return 0
        enemies = self._enemy_units(include_structures=True)
        count = 0

        # Switch harassment side occasionally so the flock does not suicide through the same static defense.
        if self._now() - self.last_muta_side_switch > 45.0:
            self.last_muta_side_switch = self._now()
            self.muta_side *= -1

        for m in list(mutas)[: self.max_units_per_step]:
            try:
                threats = self._anti_air_near(m, 8.2)
                hp_pct = float(getattr(m, "health_percentage", 1.0) or 1.0)
                if getattr(threats, "exists", False) or hp_pct < 0.38:
                    retreat = self._safe_back_point(m, threats if getattr(threats, "exists", False) else None, distance=10.0)
                    if self._issue_move(m, retreat, owner="MutaliskHarassController:retreat", priority=CommandPriority.HARASS, duration=1.8, reason="muta retreat from anti-air / low hp"):
                        count += 1
                        continue

                visible_workers = enemies.filter(lambda e: self._name(e) in {"SCV", "DRONE", "PROBE", "MULE"} and e.distance_to(m) <= 12.0) if getattr(enemies, "exists", False) else enemies
                if getattr(visible_workers, "exists", False):
                    target = min(list(visible_workers), key=lambda e: float(getattr(e, "health", 45.0) or 45.0))
                    if self._issue_attack(m, target, owner="MutaliskHarassController:worker_pickoff", priority=CommandPriority.HARASS, duration=1.5, reason="muta worker pickoff"):
                        count += 1
                        continue

                exposed = enemies.filter(lambda e: not e.is_structure and self._name(e) not in self.ANTI_AIR_THREATS and e.distance_to(m) <= 10.5) if getattr(enemies, "exists", False) else enemies
                if getattr(exposed, "exists", False):
                    target = min(list(exposed), key=lambda e: float(getattr(e, "health", 80.0) or 80.0))
                    if self._issue_attack(m, target, owner="MutaliskHarassController:pickoff", priority=CommandPriority.HARASS, duration=1.5, reason="muta pick off exposed unit"):
                        count += 1
                        continue

                # No good visible target: stay around enemy expansion side if known, otherwise follow army loosely.
                try:
                    enemy_structures = self.bot.enemy_structures
                    if enemy_structures.exists:
                        target_pos = enemy_structures.closest_to(m).position
                    else:
                        target_pos = self._army_center() or self._home_position()
                    if target_pos is not None and m.distance_to(target_pos) > 9.0:
                        # Offset slightly to avoid direct pathing into the center of the base.
                        offset = Point2((float(target_pos.x + 7.0 * self.muta_side), float(target_pos.y + 4.0 * self.muta_side)))
                        if self._issue_move(m, offset, owner="MutaliskHarassController:position", priority=CommandPriority.HARASS, duration=2.0, reason="muta harassment positioning"):
                            count += 1
                except Exception:
                    pass
            except Exception:
                continue
        return count

    # -------------------------------------------------------------------------------------
    # Corruptor / Baneling support
    # -------------------------------------------------------------------------------------
    async def _control_corruptors(self) -> int:
        bot = self.bot
        try:
            corruptors = bot.units(UnitTypeId.CORRUPTOR).ready
        except Exception:
            return 0
        if not corruptors.exists:
            return 0
        enemies = self._enemy_units(include_structures=True)
        if not getattr(enemies, "exists", False):
            return 0
        count = 0
        for c in list(corruptors)[: self.max_units_per_step]:
            try:
                air = enemies.filter(lambda e: getattr(e, "is_flying", False) and e.distance_to(c) <= 10.0)
                if air.exists:
                    target = max(list(air), key=self._score_enemy_value)
                    if self._issue_attack(c, target, owner="CorruptorController:anti_air", priority=CommandPriority.HARASS, duration=1.6, reason="corruptor focus high value air"):
                        count += 1
                        continue
                # Optional spray only when skies are clear and structure is exposed.  Ability availability
                # check prevents crashing on API naming differences.
                structures = enemies.filter(lambda e: e.is_structure and e.distance_to(c) <= 6.5)
                if structures.exists:
                    target = max(list(structures), key=self._score_enemy_value)
                    if await self._cast(c, ["CAUSTICSPRAY_CAUSTICSPRAY", "EFFECT_CAUSTICSPRAY"], target=target, key="corruptor_spray", cooldown=6.0, owner="CorruptorController:caustic_spray", priority=CommandPriority.HARASS, duration=4.0):
                        count += 1
                        continue
            except Exception:
                continue
        return count

    async def _control_banelings(self) -> int:
        bot = self.bot
        try:
            banes = bot.units(UnitTypeId.BANELING).ready
        except Exception:
            return 0
        if not banes.exists:
            return 0
        enemies = self._enemy_units()
        if not getattr(enemies, "exists", False):
            return 0
        count = 0
        for b in list(banes)[: min(self.max_units_per_step, 10)]:
            try:
                targets = enemies.filter(lambda e: self._name(e) in self.LIGHT_BIO_OR_WORKER and e.distance_to(b) <= 7.5)
                if targets.amount >= 2:
                    target = min(list(targets), key=lambda e: b.distance_to(e))
                    if self._issue_attack(b, target, owner="BanelingController:crash_light", priority=CommandPriority.HARASS, duration=1.2, reason="baneling crash into light/worker cluster"):
                        count += 1
            except Exception:
                continue
        return count

    # -------------------------------------------------------------------------------------
    # Public step
    # -------------------------------------------------------------------------------------
    async def step(self, iteration: int = 0) -> Optional[AdvancedControlSummary]:
        now = self._now()
        if now - self.last_step_time < self.interval:
            return None
        self.last_step_time = now

        counts: dict[str, int] = {}

        async def run(name: str, fn) -> int:
            try:
                n = int(await fn())
            except Exception:
                n = 0
            if n > 0:
                counts[name] = n
            return n

        actions = 0
        # Spellcasters first, then skill units, then harassment helpers.
        actions += await run("viper", self._control_vipers)
        actions += await run("infestor", self._control_infestors)
        actions += await run("ravager", self._control_ravagers)
        actions += await run("lurker", self._control_lurkers)
        actions += await run("mutalisk", self._control_mutalisks)
        actions += await run("corruptor", self._control_corruptors)
        actions += await run("baneling", self._control_banelings)

        if actions > 0:
            detail = ", ".join(f"{k}:{v}" for k, v in counts.items())
            return AdvancedControlSummary(actions=actions, reason=f"advanced controllers issued {actions} orders ({detail})", counts=counts)
        return None
