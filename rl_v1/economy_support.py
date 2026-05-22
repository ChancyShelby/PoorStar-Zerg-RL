# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from rl_v1.tech_intent import PLANS
except Exception:  # pragma: no cover
    PLANS = {}


@dataclass
class EconomySupportResult:
    moved: int = 0
    built_gas: bool = False
    assigned_gas: bool = False
    reason: str = ""


class EconomySupportManager:
    """Background economy spine for the RL wrapper.

    Important boundary:
    - RL should learn *which strategic plan* to pursue.
    - It should NOT have to rediscover basic workerflow: build enough extractors,
      put 3 workers into them, and transfer oversaturated workers to fresh bases.

    v2.8 fixes the late-game 9000 minerals / 34 gas failure mode by making gas
    infrastructure a low-frequency baseline responsibility.  This is not a fixed
    army route: the target gas count is derived from the current `rl_army_plan`
    and from emergency mineral/gas imbalance.
    """

    def __init__(self, bot, interval: float = 3.0, transfer_interval: float = 7.0):
        self.bot = bot
        self.interval = float(interval)
        self.transfer_interval = float(transfer_interval)
        self.last_step_time = -999.0
        self.last_transfer_time = -999.0
        self.last_build_gas_time = -999.0
        self.last_assign_gas_time = -999.0

    # -----------------------------------------------------------------------------------------
    # Basic counts
    # -----------------------------------------------------------------------------------------

    @staticmethod
    def _assigned(th) -> int:
        try:
            return int(getattr(th, "assigned_harvesters", 0) or 0)
        except Exception:
            return 0

    @staticmethod
    def _ideal(th) -> int:
        try:
            raw = int(getattr(th, "ideal_harvesters", 0) or 0)
        except Exception:
            raw = 16
        return max(0, min(16, raw if raw > 0 else 16))

    def _selected_plan(self):
        name = str(getattr(self.bot, "rl_army_plan", "") or "early_basic_roach_ling_bane")
        return PLANS.get(name) if PLANS else None

    def _ready_gas_count(self) -> int:
        try:
            return int(self.bot.gas_buildings.ready.amount)
        except Exception:
            try:
                return int(self.bot.gas_buildings.amount)
            except Exception:
                return 0

    def _total_gas_count(self) -> int:
        try:
            from sc2.ids.unit_typeid import UnitTypeId
            return int(self.bot.gas_buildings.amount + self.bot.already_pending(UnitTypeId.EXTRACTOR))
        except Exception:
            try:
                return int(self.bot.gas_buildings.amount)
            except Exception:
                return 0

    def _gas_worker_count(self) -> int:
        total = 0
        try:
            for g in self.bot.gas_buildings.ready:
                total += max(0, int(getattr(g, "assigned_harvesters", 0) or 0))
        except Exception:
            total = 0
        return int(total)

    def _free_geyser_count_near_bases(self) -> int:
        try:
            bases = list(self.bot.townhalls.ready)
            geysers = list(self.bot.vespene_geyser)
        except Exception:
            return 0
        used = []
        try:
            used = list(self.bot.gas_buildings)
        except Exception:
            used = []
        free = 0
        for th in bases:
            for g in geysers:
                try:
                    if g.distance_to(th) > 12.0:
                        continue
                    if any(g.distance_to(e) < 1.5 for e in used):
                        continue
                    free += 1
                except Exception:
                    continue
        return free

    def _desired_gas_count(self) -> int:
        """Desired number of extractors, not gas workers."""
        bot = self.bot
        t = float(getattr(bot, "time", 0.0) or 0.0)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        workers = 0
        bases = 0
        supply = int(getattr(bot, "supply_used", 0) or 0)
        try:
            workers = int(bot.workers.amount)
            bases = int(bot.townhalls.ready.amount)
        except Exception:
            pass

        plan = self._selected_plan()
        plan_target = int(getattr(plan, "gas_target", 2) if plan is not None else 2)
        plan_requires_hive = bool(getattr(plan, "requires_hive", False) if plan is not None else False)

        # Start conservative; early extractor trick / first gas is handled by the opening/executor gates.
        if t < 150:
            target = 1
        elif t < 240:
            target = 2
        elif t < 330:
            target = 3 if workers >= 38 else 2
        else:
            target = min(max(2, plan_target), 8)

        if t >= 390 and (workers >= 55 or supply >= 105):
            target = max(target, min(plan_target, 6))
        if t >= 480 and (workers >= 65 or supply >= 140):
            target = max(target, min(plan_target, 8))
        if plan_requires_hive and t >= 430 and bases >= 4:
            target = max(target, min(8, plan_target))

        # Hard emergency correction.  This is the specific 9000/34 bug: a plan may be
        # correct, but without gas infrastructure it can never become ultralisk/lurker/brood/viper.
        if t >= 300 and minerals >= 1200 and gas <= 250:
            target = max(target, min(6, bases * 2))
        if t >= 420 and minerals >= 1800 and gas <= 420:
            target = max(target, min(8, bases * 2))
        if t >= 540 and minerals >= 2500 and gas <= 700:
            target = max(target, min(10, bases * 2))

        # Do not ask for impossible extractors on insufficient bases.
        return int(max(0, min(target, max(0, bases * 2))))

    def _gas_emergency(self) -> bool:
        bot = self.bot
        t = float(getattr(bot, "time", 0.0) or 0.0)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        if t >= 300 and minerals >= 1200 and gas <= 250:
            return True
        if t >= 420 and minerals >= 1800 and gas <= 420:
            return True
        if t >= 540 and minerals >= 2500 and gas <= 700:
            return True
        return False

    async def _build_missing_gas(self, desired_gas_count: int) -> tuple[bool, str]:
        now = float(getattr(self.bot, "time", 0.0) or 0.0)
        if now - self.last_build_gas_time < 4.0:
            return False, "build gas cooldown"
        if self._total_gas_count() >= desired_gas_count:
            return False, "gas count already meets target"
        if self._free_geyser_count_near_bases() <= 0:
            return False, "no free geyser near ready bases"
        if int(getattr(self.bot, "minerals", 0) or 0) < 75:
            return False, "not enough minerals for extractor"
        executor = getattr(self.bot, "executor", None)
        if executor is None:
            return False, "no executor"
        try:
            res = await executor.execute("BUILD_GAS")
            self.last_build_gas_time = now
            if res is not None and res.ok:
                return True, str(getattr(res, "reason", "built gas"))
            return False, str(getattr(res, "reason", "build gas failed"))
        except Exception as exc:
            return False, f"build gas exception {type(exc).__name__}: {exc}"

    async def _assign_gas_workers_if_needed(self, desired_gas_count: int) -> tuple[bool, str]:
        now = float(getattr(self.bot, "time", 0.0) or 0.0)
        if now - self.last_assign_gas_time < 3.0:
            return False, "assign gas cooldown"
        ready = self._ready_gas_count()
        if ready <= 0:
            return False, "no ready gas"
        desired_workers = min(ready, desired_gas_count) * 3
        current = self._gas_worker_count()
        # In gas emergency, fill quickly; otherwise tolerate a small temporary deficit.
        tolerance = 0 if self._gas_emergency() else 2
        if current >= desired_workers - tolerance:
            return False, f"gas workers ok {current}/{desired_workers}"
        executor = getattr(self.bot, "executor", None)
        if executor is None:
            return False, "no executor"
        try:
            res = await executor.execute("ASSIGN_GAS_WORKERS")
            self.last_assign_gas_time = now
            if res is not None and res.ok:
                return True, str(getattr(res, "reason", "assigned gas workers"))
            return False, str(getattr(res, "reason", "assign gas failed"))
        except Exception as exc:
            return False, f"assign gas exception {type(exc).__name__}: {exc}"

    # -----------------------------------------------------------------------------------------
    # Mineral transfer support
    # -----------------------------------------------------------------------------------------

    async def _transfer_oversaturated_workers(self) -> tuple[int, str]:
        now = float(getattr(self.bot, "time", 0.0) or 0.0)
        if now - self.last_transfer_time < self.transfer_interval:
            return 0, "transfer cooldown"
        self.last_transfer_time = now

        try:
            bases = list(self.bot.townhalls.ready)
        except Exception:
            return 0, "no bases"
        if len(bases) < 2:
            return 0, "less than two bases"

        over = []
        under = []
        for th in bases:
            assigned = self._assigned(th)
            ideal = self._ideal(th)
            if ideal <= 0:
                continue
            if assigned > ideal + 3:
                over.append((assigned - ideal, th))
            elif assigned < ideal - 3:
                under.append((ideal - assigned, th))

        if not over or not under:
            return 0, "no mineral transfer needed"
        over.sort(key=lambda x: x[0], reverse=True)
        under.sort(key=lambda x: x[0], reverse=True)
        surplus, src = over[0]
        deficit, dst = under[0]
        move_n = int(max(1, min(8 if self._gas_emergency() else 6, surplus, deficit)))

        try:
            minerals = self.bot.mineral_field.closer_than(10.0, dst)
            if not minerals.exists:
                return 0, "target base has no nearby minerals"
            target_mineral = minerals.closest_to(dst)
        except Exception:
            return 0, "cannot find target mineral"

        try:
            gas_tags = set()
            for g in self.bot.gas_buildings.ready:
                gas_tags.add(int(g.tag))
            workers = self.bot.workers.filter(
                lambda w: w.tag not in self.bot.unit_tags_received_action and w.distance_to(src) <= 12.5
            )
        except Exception:
            return 0, "cannot filter workers"
        if not workers.exists:
            return 0, "no local workers"

        moved = 0
        for w in list(workers.sorted(lambda u: u.distance_to(dst)))[:move_n]:
            try:
                # Do not steal an obvious gas worker when we are already gas-starved.
                if self._gas_emergency():
                    is_gas_worker = False
                    for order in getattr(w, "orders", []) or []:
                        try:
                            if int(getattr(order, "target", -1)) in gas_tags:
                                is_gas_worker = True
                                break
                        except Exception:
                            continue
                    if is_gas_worker:
                        continue
                w.gather(target_mineral)
                moved += 1
            except Exception:
                continue
        return moved, f"transfer oversat {moved} workers from {surplus} surplus to {deficit} deficit"

    async def step(self) -> Optional[EconomySupportResult]:
        bot = self.bot
        now = float(getattr(bot, "time", 0.0) or 0.0)
        if now - self.last_step_time < self.interval:
            return None
        self.last_step_time = now

        if not getattr(bot, "workers", None) or not bot.workers.exists:
            return None

        desired_gas = self._desired_gas_count()
        before_gas_workers = self._gas_worker_count()
        total_gas = self._total_gas_count()
        ready_gas = self._ready_gas_count()
        emergency = self._gas_emergency()

        built, build_reason = await self._build_missing_gas(desired_gas)
        assigned, assign_reason = await self._assign_gas_workers_if_needed(desired_gas)
        moved, transfer_reason = await self._transfer_oversaturated_workers()
        after_gas_workers = self._gas_worker_count()

        if built or assigned or moved > 0 or emergency:
            reason = (
                f"desired_gas={desired_gas}, gas_count={total_gas}/{ready_gas}, "
                f"gas_workers={before_gas_workers}->{after_gas_workers}, emergency={emergency}, "
                f"build=({build_reason}), assign=({assign_reason}), transfer=({transfer_reason}), "
                f"bank={int(getattr(bot, 'minerals', 0) or 0)}/{int(getattr(bot, 'vespene', 0) or 0)}"
            )
            return EconomySupportResult(
                moved=int(moved),
                built_gas=bool(built),
                assigned_gas=bool(assigned),
                reason=reason,
            )
        return None
