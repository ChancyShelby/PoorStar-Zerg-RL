# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable

from rl_v1.combat_coordinator import CommandPriority, get_combat_coordinator


@dataclass
class HardScaffoldResult:
    built_gas: int = 0
    assigned_gas: int = 0
    pulled_off_gas: int = 0
    expanded: bool = False
    rallied: int = 0
    attacked: int = 0
    spent_larva: int = 0
    made_units: str = ""
    tech_actions: str = ""
    queen_actions: int = 0
    reason: str = ""


class HardScaffoldManager:
    """Non-negotiable macro scaffold for the RL wrapper.

    This manager is intentionally direct and boring.  It is not a strategy model.
    It fixes the failure mode where the bot floats 10k+ minerals, has 0~40 gas,
    leaves new bases mineral-only, and waits forever with a scattered army.

    Boundary:
    - RL may choose strategic bias later.
    - This layer always keeps extractors + gas workers + expansion/rally sane.
    """

    def __init__(self, bot):
        self.bot = bot
        self.last_step_time = -999.0
        self.last_gas_build_time = -999.0
        self.last_gas_assign_time = -999.0
        self.last_expand_time = -999.0
        self.last_rally_time = -999.0
        self.last_attack_time = -999.0
        self.last_spend_time = -999.0
        self.last_tech_time = -999.0
        self.last_queen_time = -999.0
        self.last_report_time = -999.0

    def _coord(self):
        return get_combat_coordinator(self.bot)

    def _issue_hard_attack(self, unit, target, *, owner: str, priority, duration: float, reason: str) -> bool:
        coord = self._coord()
        if coord is None:
            try:
                if unit.tag in self.bot.unit_tags_received_action:
                    return False
                unit.attack(target)
                return True
            except Exception:
                return False
        return bool(coord.issue_attack(unit, target, owner=owner, priority=priority, duration=duration, reason=reason))

    # ---------------------------------------------------------------------
    # small helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _u(name: str):
        try:
            from sc2.ids.unit_typeid import UnitTypeId
            return UnitTypeId.__members__.get(str(name).upper())
        except Exception:
            return None

    def _pending(self, unit_type) -> int:
        if unit_type is None:
            return 0
        try:
            return int(self.bot.already_pending(unit_type))
        except Exception:
            return 0

    def _ready_bases(self) -> list:
        try:
            return list(self.bot.townhalls.ready)
        except Exception:
            return []

    def _hatch_with_pending(self) -> int:
        try:
            hatch = self._u("HATCHERY")
            return int(self.bot.townhalls.amount + self._pending(hatch))
        except Exception:
            return 0

    def _ready_extractors(self) -> list:
        try:
            return list(self.bot.gas_buildings.ready)
        except Exception:
            try:
                ext = self._u("EXTRACTOR")
                return list(self.bot.structures(ext).ready) if ext is not None else []
            except Exception:
                return []

    def _extractor_with_pending(self) -> int:
        ext = self._u("EXTRACTOR")
        total = 0
        try:
            total = int(self.bot.gas_buildings.amount)
        except Exception:
            try:
                total = int(self.bot.structures(ext).amount) if ext is not None else 0
            except Exception:
                total = 0
        return int(total + self._pending(ext))

    def _is_gas_worker(self, worker, extractor_tags: set[int]) -> bool:
        try:
            for order in getattr(worker, "orders", []) or []:
                target = getattr(order, "target", None)
                try:
                    if int(target) in extractor_tags:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _gas_workers_by_unit(self) -> list:
        """Return workers that are currently ordered/assigned to our ready extractors."""
        extractors = self._ready_extractors()
        extractor_tags = {int(g.tag) for g in extractors}
        out = []
        try:
            for w in self.bot.workers:
                if self._is_gas_worker(w, extractor_tags):
                    out.append(w)
        except Exception:
            pass
        return out

    def _mineral_target_for_worker(self, worker):
        bot = self.bot
        try:
            if bot.mineral_field.exists:
                return bot.mineral_field.closest_to(worker)
        except Exception:
            pass
        try:
            bases = list(bot.townhalls.ready)
            if bases:
                th = min(bases, key=lambda b: b.distance_to(worker))
                minerals = bot.mineral_field.closer_than(12.0, th)
                if minerals.exists:
                    return minerals.closest_to(th)
        except Exception:
            pass
        return None

    def _gas_worker_count(self) -> int:
        extractors = self._ready_extractors()
        extractor_tags = {int(g.tag) for g in extractors}
        assigned = 0
        try:
            for gas in extractors:
                assigned += max(0, int(getattr(gas, "assigned_harvesters", 0) or 0))
        except Exception:
            assigned = 0
        by_orders = 0
        try:
            for w in self.bot.workers:
                if self._is_gas_worker(w, extractor_tags):
                    by_orders += 1
        except Exception:
            pass
        return int(max(assigned, by_orders))

    def _worker_candidates(self, pos=None, allow_busy_fallback: bool = True) -> list:
        try:
            workers = list(self.bot.workers)
        except Exception:
            return []
        received = set(getattr(self.bot, "unit_tags_received_action", set()) or set())

        def ok_primary(w) -> bool:
            try:
                return int(w.tag) not in received and (getattr(w, "is_collecting", False) or getattr(w, "is_idle", False))
            except Exception:
                return False

        cands = [w for w in workers if ok_primary(w)]
        if not cands and allow_busy_fallback:
            # Late-game recovery fallback: if every worker is already carrying/returning, still
            # steal a worker.  Otherwise a gas emergency can deadlock forever.
            cands = [w for w in workers if int(getattr(w, "tag", -1)) not in received]
        if not cands and allow_busy_fallback:
            cands = list(workers)
        if pos is not None:
            try:
                cands.sort(key=lambda w: w.distance_to(pos))
            except Exception:
                pass
        return cands

    def _free_geysers(self) -> list:
        bases = self._ready_bases()
        if not bases:
            return []
        try:
            geysers = list(self.bot.vespene_geyser)
        except Exception:
            return []
        try:
            existing = list(self.bot.gas_buildings)
        except Exception:
            existing = []
        free = []
        for th in bases:
            for g in geysers:
                try:
                    if g.distance_to(th) > 12.0:
                        continue
                    if any(g.distance_to(e) < 1.5 for e in existing):
                        continue
                    free.append((th, g))
                except Exception:
                    continue
        # De-duplicate geysers seen from overlapping bases.
        seen = set()
        out = []
        for th, g in free:
            try:
                tag = int(g.tag)
            except Exception:
                tag = id(g)
            if tag in seen:
                continue
            seen.add(tag)
            out.append((th, g))
        return out

    def _desired_extractors(self) -> int:
        bot = self.bot
        t = float(getattr(bot, "time", 0.0) or 0.0)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        supply = int(getattr(bot, "supply_used", 0) or 0)
        try:
            workers = int(bot.workers.amount)
        except Exception:
            workers = 0
        bases = len(self._ready_bases())
        if bases <= 0:
            return 0

        # Extractor count and gas-worker count are intentionally separate.
        # Do not build 4 gases just because minerals are 700 if gas is already floating.
        target = 1
        if t >= 210 or workers >= 30 or supply >= 50 or bases >= 3:
            target = 2
        if t >= 360 or workers >= 48 or supply >= 95:
            target = 4
        if t >= 500 or workers >= 62 or supply >= 130:
            target = 6
        if t >= 650 or workers >= 74 or supply >= 165:
            target = 8

        # Low-gas emergency: this is the previous 13k minerals / 38 gas failure mode.
        if (t >= 300 and minerals >= 1000 and gas <= 250) or (minerals >= 2500 and gas <= 900):
            target = max(target, min(8, bases * 2))
        if (t >= 520 and minerals >= 2000 and gas <= 700) or (minerals >= 5000 and gas <= 1600):
            target = max(target, min(10, bases * 2))
        if minerals >= 9000 and gas <= 1800:
            target = max(target, min(12, bases * 2))

        # v3.2 anti-overcorrection: gas flood + mineral starvation means "stop making more gases".
        if gas >= 600 and minerals <= 350:
            target = min(target, max(1, self._extractor_with_pending()))
        if supply < 60 and gas >= 450 and minerals < 500:
            target = min(target, 1)

        return int(max(0, min(target, bases * 2)))

    def _desired_gas_workers(self, desired_extractors: int) -> int:
        """Target gas workers, separate from extractor count.

        v3.2 fix: v3.0/v3.1 solved low-gas games by always filling extractors,
        but that overcorrects into screenshots like 29 minerals / 1031 gas / 24 supply.
        Extractors may exist, but workers must be pulled off gas when mineral-starved.
        """
        bot = self.bot
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        supply = int(getattr(bot, "supply_used", 0) or 0)
        t = float(getattr(bot, "time", 0.0) or 0.0)
        ready = len(self._ready_extractors())
        cap = max(0, min(int(desired_extractors), ready) * 3)
        if cap <= 0:
            return 0

        # Absolute mineral starvation: stop gas completely until minerals recover.
        if minerals <= 80 and gas >= 250:
            return 0
        if minerals <= 150 and gas >= 400:
            return min(1, cap)

        # Early-game gas flood is deadly: every drone on gas delays queens/lings/overlords/hatcheries.
        if supply < 45 and gas >= 300 and minerals < 450:
            return min(1, cap)
        if supply < 70 and gas >= 550 and minerals < 650:
            return min(2, cap)

        # General stockpile rebalance.  If gas greatly exceeds minerals, mine minerals first.
        if gas >= minerals + 900 and minerals < 1000:
            return min(3, cap)
        if gas >= minerals + 500 and minerals < 700:
            return min(max(1, ready), cap)

        # Normal staged saturation.
        if t < 210 and gas >= 180 and minerals < 350:
            return min(1, cap)
        return cap

    def _target_bases(self) -> int:
        bot = self.bot
        t = float(getattr(bot, "time", 0.0) or 0.0)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        supply = int(getattr(bot, "supply_used", 0) or 0)
        try:
            workers = int(bot.workers.amount)
        except Exception:
            workers = 0
        target = 2
        if t >= 170 or workers >= 28 or supply >= 40 or minerals >= 360:
            target = 3
        if t >= 390 or workers >= 50 or supply >= 85 or minerals >= 800:
            target = 4
        if t >= 520 or workers >= 64 or supply >= 125 or minerals >= 1200:
            target = 5
        if t >= 660 or workers >= 74 or supply >= 160 or minerals >= 1800:
            target = 6
        if minerals >= 3500 or supply >= 185:
            target = 7
        if minerals >= 7000:
            target = 8
        return int(min(target, 8))

    # ---------------------------------------------------------------------
    # gas / expansion / rally operations
    # ---------------------------------------------------------------------
    async def _build_gas_direct(self, desired: int) -> tuple[int, str]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_gas_build_time < 2.5:
            return 0, "gas build cooldown"
        if self._extractor_with_pending() >= desired:
            return 0, f"gas count ok {self._extractor_with_pending()}/{desired}"
        if int(getattr(bot, "minerals", 0) or 0) < 75:
            return 0, "not enough minerals"
        ext = self._u("EXTRACTOR")
        if ext is None:
            return 0, "UnitTypeId.EXTRACTOR missing"

        free = self._free_geysers()
        if not free:
            return 0, "no free geyser near ready bases"

        # Prefer bases with fewer gases; if we are late, new/far bases still get gas.
        def score(pair):
            th, g = pair
            try:
                local = self.bot.gas_buildings.closer_than(12.0, th).amount
            except Exception:
                local = 0
            try:
                assigned = int(getattr(th, "assigned_harvesters", 0) or 0)
                ideal = int(getattr(th, "ideal_harvesters", 16) or 16)
            except Exception:
                assigned, ideal = 0, 16
            try:
                dist = float(g.distance_to(th))
            except Exception:
                dist = 99.0
            return (local, -min(assigned, ideal), dist)

        free.sort(key=score)
        need = max(0, desired - self._extractor_with_pending())
        max_builds = 2 if int(getattr(bot, "minerals", 0) or 0) >= 1200 else 1
        built = 0
        reasons = []
        used_workers = set()
        for _, geyser in free[:max_builds]:
            if built >= need:
                break
            workers = [w for w in self._worker_candidates(geyser, allow_busy_fallback=True) if int(getattr(w, "tag", -1)) not in used_workers]
            if not workers:
                reasons.append("no worker for geyser")
                continue
            worker = workers[0]
            try:
                worker.build(ext, geyser)
                used_workers.add(int(worker.tag))
                built += 1
                reasons.append(f"build extractor at ({geyser.position.x:.1f},{geyser.position.y:.1f})")
            except Exception as exc:
                reasons.append(f"build gas failed: {type(exc).__name__}: {exc}")
                continue
        if built > 0:
            self.last_gas_build_time = now
        return built, "; ".join(reasons) or "no build issued"

    async def _assign_gas_direct(self, desired_extractors: int, desired_workers: int) -> tuple[int, int, str]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_gas_assign_time < 1.2:
            return 0, 0, "gas assign cooldown"
        ready_all = self._ready_extractors()
        if not ready_all:
            return 0, 0, "no ready extractor"

        bases = self._ready_bases()
        if bases:
            try:
                ready_all.sort(key=lambda g: min(g.distance_to(th) for th in bases))
            except Exception:
                pass

        all_extractor_tags = {int(g.tag) for g in ready_all}
        current_total = self._gas_worker_count()
        desired_workers = max(0, int(desired_workers))

        moved_to_gas = 0
        pulled_off_gas = 0
        reasons = []
        used = set()

        # v3.2: if gas is already flooding, actively pull drones back to minerals.
        # Merely "not assigning more" is not enough because existing gas orders persist.
        if current_total > desired_workers:
            excess = current_total - desired_workers
            gas_workers = self._gas_workers_by_unit()
            # Prefer pulling workers near outer bases last? Simpler and safer: nearest mineral target per worker.
            for worker in gas_workers[:excess]:
                if int(getattr(worker, "tag", -1)) in used:
                    continue
                target = self._mineral_target_for_worker(worker)
                if target is None:
                    continue
                try:
                    worker.gather(target)
                    used.add(int(worker.tag))
                    pulled_off_gas += 1
                except Exception as exc:
                    reasons.append(f"pull off gas failed: {type(exc).__name__}: {exc}")
                    continue
            current_total = max(0, current_total - pulled_off_gas)

        if current_total >= desired_workers:
            if pulled_off_gas > 0:
                self.last_gas_assign_time = now
            reasons.append(f"gas worker target reached current={current_total}, target={desired_workers}, pulled={pulled_off_gas}")
            return 0, pulled_off_gas, "; ".join(reasons)

        # Fill only the number of gas workers requested by balance logic.
        ready = ready_all[:max(0, int(desired_extractors))]
        by_order = {int(g.tag): 0 for g in ready}
        try:
            for w in bot.workers:
                for order in getattr(w, "orders", []) or []:
                    try:
                        tag = int(getattr(order, "target", -1))
                    except Exception:
                        continue
                    if tag in by_order:
                        by_order[tag] += 1
                        break
        except Exception:
            pass

        need_total = max(0, desired_workers - current_total)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        emergency_low_gas = bool((minerals >= 1000 and gas <= 350) or minerals >= 2500)
        max_moves = min(20 if emergency_low_gas else 8, need_total)

        for gas_building in ready:
            if moved_to_gas >= max_moves:
                break
            try:
                tag = int(gas_building.tag)
                assigned_api = int(getattr(gas_building, "assigned_harvesters", 0) or 0)
            except Exception:
                continue
            current_here = max(assigned_api, int(by_order.get(tag, 0)))
            while current_here < 3 and moved_to_gas < max_moves:
                workers = self._worker_candidates(gas_building, allow_busy_fallback=True)
                workers = [
                    w for w in workers
                    if int(getattr(w, "tag", -1)) not in used
                    and not self._is_gas_worker(w, all_extractor_tags)
                ]
                if not workers:
                    break
                worker = workers[0]
                try:
                    worker.gather(gas_building)
                    used.add(int(worker.tag))
                    moved_to_gas += 1
                    current_here += 1
                except Exception as exc:
                    reasons.append(f"assign failed: {type(exc).__name__}: {exc}")
                    break

        if moved_to_gas > 0 or pulled_off_gas > 0:
            self.last_gas_assign_time = now
            reasons.append(
                f"gas rebalance: to_gas={moved_to_gas}, off_gas={pulled_off_gas}, "
                f"current_before={self._gas_worker_count()}, target_workers={desired_workers}, "
                f"ready_extractors={len(ready_all)}, desired_extractors={desired_extractors}"
            )
        else:
            reasons.append(
                f"gas workers ok/blocked: current={self._gas_worker_count()}, "
                f"target_workers={desired_workers}, ready={len(ready_all)}, desired_extractors={desired_extractors}"
            )
        return moved_to_gas, pulled_off_gas, "; ".join(reasons)

    async def _expand_if_needed(self) -> tuple[bool, str]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_expand_time < 14.0:
            return False, "expand cooldown"
        target = self._target_bases()
        current = self._hatch_with_pending()
        if current >= target:
            return False, f"bases ok {current}/{target}"
        if int(getattr(bot, "minerals", 0) or 0) < 300:
            return False, "not enough minerals for hatchery"
        # Don't spam expand attempts while a hatch is already pending.
        hatch = self._u("HATCHERY")
        try:
            if self._pending(hatch) > 0:
                return False, "hatch already pending"
        except Exception:
            pass
        try:
            # Use python-sc2's own placement first.  This is slower than direct worker.build,
            # but much safer across maps and avoids hand-rolled placement.
            await bot.expand_now()
            self.last_expand_time = now
            return True, f"expand_now for base {current + 1}/{target}"
        except Exception as exc:
            self.last_expand_time = now
            return False, f"expand_now failed: {type(exc).__name__}: {exc}"

    @staticmethod
    def _combat_names() -> set[str]:
        return {
            "ZERGLING", "BANELING", "ROACH", "RAVAGER", "HYDRALISK", "MUTALISK", "CORRUPTOR",
            "INFESTOR", "VIPER", "ULTRALISK", "BROODLORD", "LURKERMP", "LURKER",
            "SWARMHOSTMP", "SWARMHOST", "QUEEN",
        }

    def _combat_units(self, include_queens: bool = False) -> list:
        ids = []
        for name in self._combat_names():
            if name == "QUEEN" and not include_queens:
                continue
            u = self._u(name)
            if u is not None:
                ids.append(u)
        units = []
        try:
            for u in ids:
                units.extend(list(self.bot.units(u)))
        except Exception:
            return []
        return units

    def _enemy_target(self):
        bot = self.bot
        tactical = getattr(bot, "tactical_targeting", None)
        if tactical is not None:
            try:
                target = tactical.get_attack_target(force_rotate=False)
                if target is not None:
                    return target
            except Exception:
                pass
        try:
            if bot.enemy_structures.exists:
                army = self._combat_units(include_queens=False)
                ref = army[0] if army else bot.start_location
                return bot.enemy_structures.closest_to(ref)
        except Exception:
            pass
        try:
            return bot.enemy_start_locations[0]
        except Exception:
            return None

    def _rally_point(self):
        bot = self.bot
        try:
            enemy = bot.enemy_start_locations[0]
            start = bot.start_location
            # 60% toward enemy; safe enough as staging point, not inside enemy main.
            return start.towards(enemy, start.distance_to(enemy) * 0.60)
        except Exception:
            try:
                return bot.game_info.map_center
            except Exception:
                return None

    async def _rally_or_attack(self) -> tuple[int, int, str]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        supply = int(getattr(bot, "supply_used", 0) or 0)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        army = self._combat_units(include_queens=False)
        if len(army) < 14:
            return 0, 0, "not enough army to rally"

        target = self._enemy_target()
        rally = self._rally_point()
        if target is None and rally is None:
            return 0, 0, "no target/rally"

        # Attack: near max or absurd bank means sitting is worse than a bad attack.
        attack_due = bool(supply >= 188 or (supply >= 160 and minerals >= 2500) or minerals >= 7000)
        if attack_due and now - self.last_attack_time >= 10.0 and target is not None:
            issued = 0
            for unit in army[:120]:
                if self._issue_hard_attack(
                    unit,
                    target,
                    owner="HardScaffoldAttack",
                    priority=CommandPriority.ARMY_ATTACK,
                    duration=1.5,
                    reason="hard scaffold force attack",
                ):
                    issued += 1
            if issued > 0:
                self.last_attack_time = now
                return 0, issued, f"force attack: supply={supply}, bank={minerals}/{gas}, units={issued}"

        # Rally only idle/local units so we do not constantly override real combat.
        if now - self.last_rally_time < 5.0 or rally is None:
            return 0, 0, "rally cooldown"
        idle = []
        for unit in army:
            try:
                if getattr(unit, "is_idle", False) or len(getattr(unit, "orders", []) or []) == 0:
                    idle.append(unit)
            except Exception:
                pass
        if len(idle) < 6:
            return 0, 0, "few idle army"
        issued = 0
        for unit in idle[:80]:
            if self._issue_hard_attack(
                unit,
                rally,
                owner="HardScaffoldRally",
                priority=CommandPriority.RALLY,
                duration=1.5,
                reason="hard scaffold idle rally",
            ):
                issued += 1
        if issued > 0:
            self.last_rally_time = now
            return issued, 0, f"rally idle army to staging point, units={issued}"
        return 0, 0, "rally failed"


    # ---------------------------------------------------------------------
    # hard spend / production operations
    # ---------------------------------------------------------------------
    def _structures_ready(self, name: str) -> bool:
        unit_type = self._u(name)
        if unit_type is None:
            return False
        try:
            return bool(self.bot.structures(unit_type).ready.exists)
        except Exception:
            return False

    def _units_count(self, name: str) -> int:
        unit_type = self._u(name)
        if unit_type is None:
            return 0
        try:
            return int(self.bot.units(unit_type).amount)
        except Exception:
            return 0

    def _larva_available(self) -> list:
        try:
            received = set(getattr(self.bot, "unit_tags_received_action", set()) or set())
            return list(self.bot.larva.filter(lambda u: u.tag not in received))
        except Exception:
            try:
                return list(self.bot.larva)
            except Exception:
                return []

    def _can_train_unit(self, unit_name: str, supply_required: int = 1) -> tuple[bool, str]:
        bot = self.bot
        unit_type = self._u(unit_name)
        if unit_type is None:
            return False, f"{unit_name} id missing"
        if int(getattr(bot, "supply_left", 0) or 0) < supply_required:
            return False, f"not enough supply for {unit_name}"
        try:
            if not bot.can_afford(unit_type):
                return False, f"cannot afford {unit_name}"
        except Exception as exc:
            return False, f"can_afford failed {unit_name}: {type(exc).__name__}: {exc}"
        return True, "ok"

    def _choose_spend_unit(self, made: dict[str, int]) -> tuple[object | None, str, int, str]:
        """Return (UnitTypeId, printable_name, supply_required, reason)."""
        bot = self.bot
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        supply_left = int(getattr(bot, "supply_left", 0) or 0)
        t = float(getattr(bot, "time", 0.0) or 0.0)

        def candidate(name: str, supply: int, req: bool = True, cap: int | None = None):
            if not req:
                return None
            if cap is not None and self._units_count(name) + int(made.get(name, 0)) >= cap:
                return None
            ok, why = self._can_train_unit(name, supply)
            if not ok:
                return None
            return self._u(name), name, supply, why

        # 魔法/高级兵只做少量上限，防止不会操作的单位塞满人口。
        if t >= 620 and gas >= 500 and supply_left >= 6:
            c = candidate("ULTRALISK", 6, req=self._structures_ready("HIVE") and self._structures_ready("ULTRALISKCAVERN"), cap=8)
            if c:
                return c
        if t >= 560 and gas >= 450 and supply_left >= 3:
            c = candidate("VIPER", 3, req=self._structures_ready("HIVE") and self._structures_ready("INFESTATIONPIT"), cap=4)
            if c:
                return c
        if t >= 520 and gas >= 350 and supply_left >= 2:
            c = candidate("INFESTOR", 2, req=self._structures_ready("LAIR") or self._structures_ready("HIVE"), cap=4)
            # infestor 需要感染虫巢。这里不能只看 lair/hive。
            if c and self._structures_ready("INFESTATIONPIT"):
                return c
        if gas >= 250 and supply_left >= 2:
            c = candidate("CORRUPTOR", 2, req=self._structures_ready("SPIRE") or self._structures_ready("GREATERSPIRE"), cap=16)
            if c:
                return c

        # 主力消耗资源：优先刺蛇/蟑螂，不让 2k/1.6k 这种银行继续躺着。
        if gas >= 120 and supply_left >= 2:
            c = candidate("HYDRALISK", 2, req=self._structures_ready("HYDRALISKDEN"))
            if c:
                return c
        if gas >= 75 and supply_left >= 2:
            c = candidate("ROACH", 2, req=self._structures_ready("ROACHWARREN"))
            if c:
                return c
        if gas >= 100 and supply_left >= 2:
            c = candidate("MUTALISK", 2, req=self._structures_ready("SPIRE") or self._structures_ready("GREATERSPIRE"), cap=18)
            if c:
                return c

        # 没科技也不能发呆：至少用小狗把钱转成战斗力。
        if minerals >= 100 and supply_left >= 1:
            c = candidate("ZERGLING", 1, req=self._structures_ready("SPAWNINGPOOL"))
            if c:
                return c
        return None, "", 0, "no trainable combat unit"

    async def _train_queens_if_needed(self) -> tuple[int, str]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_queen_time < 4.0:
            return 0, "queen cooldown"
        if not self._structures_ready("SPAWNINGPOOL"):
            return 0, "pool not ready"
        queen = self._u("QUEEN")
        if queen is None:
            return 0, "queen id missing"
        try:
            bases = list(bot.townhalls.ready.idle)
        except Exception:
            bases = []
        if not bases:
            return 0, "no idle hatch for queen"
        try:
            current_queens = int(bot.units(queen).amount + bot.already_pending(queen))
        except Exception:
            current_queens = 0
        desired = max(2, min(8, len(self._ready_bases()) + 2))
        if current_queens >= desired:
            return 0, f"queens ok {current_queens}/{desired}"
        made = 0
        for hatch in bases[:2]:
            if current_queens + made >= desired:
                break
            try:
                if int(getattr(bot, "supply_left", 0) or 0) < 2 or not bot.can_afford(queen):
                    break
                hatch.train(queen)
                made += 1
            except Exception:
                continue
        if made > 0:
            self.last_queen_time = now
        return made, f"queued queens={made}, target={desired}"

    async def _force_tech_if_needed(self) -> tuple[str, str]:
        """Force the minimal tech chain so late bank can become real units."""
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_tech_time < 6.0:
            return "", "tech cooldown"
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        executor = getattr(bot, "executor", None)
        if executor is None:
            return "", "no executor"

        actions: list[str] = []
        # 这里是兜底科技链，不追求花哨，只保证：蟑螂->二本->刺蛇->感染虫巢->三本->高阶单位。
        if now >= 220 and minerals >= 150 and not self._structures_ready("ROACHWARREN"):
            actions.append("BUILD_ROACH_WARREN")
        if now >= 260 and minerals >= 150 and gas >= 100 and not (self._structures_ready("LAIR") or self._structures_ready("HIVE")):
            actions.append("MORPH_LAIR")
        if now >= 360 and minerals >= 100 and gas >= 100 and (self._structures_ready("LAIR") or self._structures_ready("HIVE")) and not self._structures_ready("HYDRALISKDEN"):
            actions.append("BUILD_HYDRA_DEN")
        if now >= 470 and minerals >= 100 and gas >= 100 and (self._structures_ready("LAIR") or self._structures_ready("HIVE")) and not self._structures_ready("INFESTATIONPIT"):
            actions.append("BUILD_INFESTATION_PIT")
        if now >= 560 and minerals >= 200 and gas >= 150 and self._structures_ready("INFESTATIONPIT") and not self._structures_ready("HIVE"):
            actions.append("MORPH_HIVE")
        if now >= 650 and minerals >= 150 and gas >= 150 and self._structures_ready("HIVE") and not self._structures_ready("ULTRALISKCAVERN"):
            actions.append("BUILD_ULTRALISK_CAVERN")
        if now >= 500 and minerals >= 150 and gas >= 150 and (self._structures_ready("LAIR") or self._structures_ready("HIVE")) and not (self._structures_ready("SPIRE") or self._structures_ready("GREATERSPIRE")):
            # 只有资源大量积压时才补飞龙塔，避免过早打乱蟑螂刺蛇主线。
            if minerals >= 1200 or gas >= 700:
                actions.append("BUILD_SPIRE")

        reasons = []
        done = []
        for action in actions[:2]:
            try:
                res = await executor.execute(action)
                reasons.append(f"{action}:{getattr(res, 'ok', False)}:{getattr(res, 'reason', '')}")
                if getattr(res, "ok", False):
                    done.append(action)
            except Exception as exc:
                reasons.append(f"{action}:ERR:{type(exc).__name__}:{exc}")
        if done:
            self.last_tech_time = now
        return "+".join(done), "; ".join(reasons) if reasons else "no tech due"

    async def _morph_lurkers_if_needed(self) -> tuple[int, str]:
        bot = self.bot
        executor = getattr(bot, "executor", None)
        if executor is None:
            return 0, "no executor"
        if not (self._structures_ready("LURKERDENMP") or self._structures_ready("LURKERDEN")):
            return 0, "lurker den not ready"
        if int(getattr(bot, "vespene", 0) or 0) < 200:
            return 0, "not enough gas for lurkers"
        current = self._units_count("LURKERMP") + self._units_count("LURKER")
        if current >= 10:
            return 0, "lurkers capped"
        made = 0
        # 不要一口气把所有刺蛇变完；先转 3-5 个。
        for _ in range(min(5 - current, 3)):
            try:
                res = await executor.execute("MORPH_LURKER")
                if getattr(res, "ok", False):
                    made += 1
                else:
                    break
            except Exception:
                break
        return made, f"morph_lurker={made}"

    async def _spend_bank_direct(self) -> tuple[int, str, str]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_spend_time < 0.7:
            return 0, "", "spend cooldown"

        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        supply_left = int(getattr(bot, "supply_left", 0) or 0)
        supply_cap = int(getattr(bot, "supply_cap", 0) or 0)
        supply_used = int(getattr(bot, "supply_used", 0) or 0)
        larva = self._larva_available()

        # Not a crisis: do not steal every normal macro step.
        bank_crisis = bool(minerals >= 900 or gas >= 650 or (minerals >= 600 and supply_left >= 12 and len(larva) >= 6))
        if not bank_crisis:
            return 0, "", f"no bank crisis bank={minerals}/{gas}, larva={len(larva)}"

        executor = getattr(bot, "executor", None)
        pre_actions = []
        # If supply is the only blocker, queue overlords first.
        if supply_cap < 200 and (supply_left <= 6 or (len(larva) >= supply_left and minerals >= 800)) and executor is not None:
            for _ in range(2 if minerals >= 1000 else 1):
                try:
                    res = await executor.execute("MAKE_OVERLORD")
                    pre_actions.append(f"OVERLORD:{getattr(res, 'ok', False)}:{getattr(res, 'reason', '')}")
                except Exception as exc:
                    pre_actions.append(f"OVERLORD:ERR:{type(exc).__name__}:{exc}")

        tech_done, tech_reason = await self._force_tech_if_needed()
        queen_count, queen_reason = await self._train_queens_if_needed()
        lurker_count, lurker_reason = await self._morph_lurkers_if_needed()

        larva = self._larva_available()
        if not larva:
            # With zero larva, the best immediate spending is extra queens/tech/expansion already handled above.
            reason = f"no larva; pre={pre_actions}; tech=({tech_reason}); queens=({queen_reason}); lurkers=({lurker_reason})"
            made_units = []
            if queen_count:
                made_units.append(f"QUEEN:{queen_count}")
            if lurker_count:
                made_units.append(f"LURKER:{lurker_count}")
            return queen_count + lurker_count, ",".join(made_units), reason

        # High-bank Zerg must spend many larva in the same on_step; one unit/second is far too slow.
        max_larva_to_spend = min(len(larva), 14 if minerals >= 2000 or gas >= 1200 else 9)
        made: dict[str, int] = {}
        used = 0
        reasons = []
        for larva_unit in larva[:max_larva_to_spend]:
            unit_type, name, supply_req, why = self._choose_spend_unit(made)
            if unit_type is None:
                reasons.append(why)
                break
            try:
                larva_unit.train(unit_type)
                made[name] = made.get(name, 0) + 1
                used += 1
            except Exception as exc:
                reasons.append(f"train {name} failed: {type(exc).__name__}: {exc}")
                break

        if used > 0 or queen_count > 0 or lurker_count > 0 or tech_done:
            self.last_spend_time = now
        made_units = ",".join(f"{k}:{v}" for k, v in sorted(made.items()))
        extra_units = []
        if queen_count:
            extra_units.append(f"QUEEN:{queen_count}")
        if lurker_count:
            extra_units.append(f"LURKER:{lurker_count}")
        if extra_units:
            made_units = ",".join([x for x in [made_units, *extra_units] if x])
        reason = (
            f"spent_larva={used}/{len(larva)}, units={made_units or 'none'}, bank={minerals}/{gas}, "
            f"supply={supply_used}/{supply_cap}, supply_left={supply_left}; pre={pre_actions}; "
            f"tech=({tech_reason}); queens=({queen_reason}); lurkers=({lurker_reason}); "
            f"tail={'; '.join(reasons[-2:])}"
        )
        return used + queen_count + lurker_count, made_units, reason

    # ---------------------------------------------------------------------
    # public step
    # ---------------------------------------------------------------------
    async def step(self, iteration: int = 0) -> Optional[HardScaffoldResult]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now < 150.0:
            return None
        if now - self.last_step_time < 1.0:
            return None
        self.last_step_time = now

        desired_gas = self._desired_extractors()
        desired_gas_workers = self._desired_gas_workers(desired_gas)
        built, build_reason = await self._build_gas_direct(desired_gas)
        assigned, pulled_off_gas, assign_reason = await self._assign_gas_direct(desired_gas, desired_gas_workers)
        expanded, expand_reason = await self._expand_if_needed()
        spent, made_units, spend_reason = await self._spend_bank_direct()
        rallied, attacked, rally_reason = await self._rally_or_attack()

        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        current_gas = self._extractor_with_pending()
        ready_gas = len(self._ready_extractors())
        gas_workers = self._gas_worker_count()
        reason = (
            f"desired_gas={desired_gas}, target_gas_workers={desired_gas_workers}, "
            f"gas={current_gas}/{ready_gas}, gas_workers={gas_workers}, "
            f"bank={minerals}/{gas}; build=({build_reason}); assign=({assign_reason}); "
            f"expand=({expand_reason}); spend=({spend_reason}); army=({rally_reason})"
        )

        # Return only if something happened, or periodically during crisis so the logs expose it.
        crisis = bool((minerals >= 1000 and gas <= 350) or minerals >= 2500 or gas >= 900)
        if built or assigned or pulled_off_gas or expanded or spent or rallied or attacked or (crisis and now - self.last_report_time >= 20.0):
            self.last_report_time = now
            return HardScaffoldResult(
                built_gas=int(built),
                assigned_gas=int(assigned),
                pulled_off_gas=int(pulled_off_gas),
                expanded=bool(expanded),
                rallied=int(rallied),
                attacked=int(attacked),
                spent_larva=int(spent),
                made_units=str(made_units),
                tech_actions="",
                queen_actions=0,
                reason=reason,
            )
        return None
