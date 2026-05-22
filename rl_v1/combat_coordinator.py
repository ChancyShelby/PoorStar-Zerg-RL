# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Combat command arbitration for the RL wrapper.

This module is intentionally small and dependency-light.  It does not try to be a
micro controller.  Its job is to prevent the current problem: several managers
issuing contradictory commands to the same unit in the same/nearby frames.

Core ideas:
- Every combat command has an owner.
- Every owner has a priority.
- Higher priority may preempt lower priority.
- Same owner may refresh its own claim.
- Claims expire automatically, so a failed/old controller cannot permanently
  freeze units.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Iterable, Optional

try:
    from sc2.ids.unit_typeid import UnitTypeId
except Exception:  # pragma: no cover - keeps import safe in non-SC2 tooling
    UnitTypeId = None  # type: ignore


class CommandPriority(IntEnum):
    """Higher number means stronger right to command a unit."""

    OBSERVE = 0
    RALLY = 20
    GENERIC_MICRO = 30
    ARMY_ATTACK = 40
    HARASS = 50
    SPECIAL_RESERVE = 60
    SPELLCAST = 70
    BASE_DEFENSE = 80
    WORKER_DEFENSE = 85
    EMERGENCY_RETREAT = 100


@dataclass
class UnitClaim:
    tag: int
    owner: str
    priority: int
    expires_at: float
    reason: str = ""
    action: str = ""
    target: str = ""
    issued_at: float = 0.0


@dataclass
class CommandIssue:
    ok: bool
    reason: str
    owner: str = ""
    priority: int = 0
    previous_owner: str = ""
    previous_priority: int = 0


class CombatCoordinator:
    """Unit ownership + command priority arbiter.

    Attach this to `bot.combat_coordinator`.  Existing managers can use
    `issue_attack/issue_move/issue_ability`, while old managers that have not yet
    been migrated will still work because all methods fail open when something is
    unavailable.
    """

    DEFAULT_PROTECTED_TYPE_NAMES = {
        # These should not be dragged by generic all-army A-move.  Later dedicated
        # controllers can claim them with SPELLCAST/HARASS priority.
        "VIPER",
        "INFESTOR",
        "INFESTORBURROWED",
        "LURKERMP",
        "LURKER",
        "LURKERMPBURROWED",
        "LURKERBURROWED",
        "MUTALISK",
        "CORRUPTOR",
        "BROODLORD",
    }

    def __init__(
        self,
        bot,
        default_claim_seconds: float = 1.6,
        special_reserve_seconds: float = 2.2,
        log_interval: float = 18.0,
        enable_special_reserve: bool = True,
    ):
        self.bot = bot
        self.default_claim_seconds = float(default_claim_seconds)
        self.special_reserve_seconds = float(special_reserve_seconds)
        self.log_interval = float(log_interval)
        self.enable_special_reserve = bool(enable_special_reserve)

        self.claims: Dict[int, UnitClaim] = {}
        self.iteration: int = 0
        self.last_log_time: float = -999.0
        self.frame_requests: int = 0
        self.frame_issued: int = 0
        self.frame_blocked: int = 0
        self.frame_preemptions: int = 0
        self.total_issued: int = 0
        self.total_blocked: int = 0
        self.total_preemptions: int = 0
        self.owner_issue_count: Dict[str, int] = {}
        self.owner_block_count: Dict[str, int] = {}

    # -----------------------------------------------------------------------------------------
    # Lifecycle / cleanup
    # -----------------------------------------------------------------------------------------
    def now(self) -> float:
        try:
            return float(getattr(self.bot, "time", 0.0) or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _tag(unit_or_tag: Any) -> Optional[int]:
        if unit_or_tag is None:
            return None
        try:
            return int(getattr(unit_or_tag, "tag"))
        except Exception:
            try:
                return int(unit_or_tag)
            except Exception:
                return None

    def cleanup_expired(self) -> None:
        now = self.now()
        expired = [tag for tag, claim in self.claims.items() if claim.expires_at <= now]
        for tag in expired:
            self.claims.pop(tag, None)

    def begin_step(self, iteration: int = 0) -> None:
        # First report/clean the previous frame's arbitration state, then reset
        # frame counters for the new decision tick.  RLPoorStarBot has many early
        # returns, so relying on an explicit end_step() would miss logs.
        self.cleanup_expired()
        self._maybe_log()
        self.iteration = int(iteration)
        self.frame_requests = 0
        self.frame_issued = 0
        self.frame_blocked = 0
        self.frame_preemptions = 0
        if self.enable_special_reserve:
            self.reserve_special_units()

    def end_step(self) -> None:
        self.cleanup_expired()
        self._maybe_log()

    def _maybe_log(self) -> None:
        now = self.now()
        quiet = bool(getattr(self.bot, "quiet", False))
        if quiet or now - self.last_log_time < self.log_interval:
            return
        self.last_log_time = now
        active_by_owner: Dict[str, int] = {}
        for claim in self.claims.values():
            active_by_owner[claim.owner] = active_by_owner.get(claim.owner, 0) + 1
        if self.frame_requests or self.claims:
            try:
                print(
                    f"[{now:06.1f}] COMBAT_COORD "
                    f"issued={self.frame_issued} blocked={self.frame_blocked} preempt={self.frame_preemptions} "
                    f"active={active_by_owner}"
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------------------------
    # Ownership
    # -----------------------------------------------------------------------------------------
    def current_claim(self, unit_or_tag: Any) -> Optional[UnitClaim]:
        tag = self._tag(unit_or_tag)
        if tag is None:
            return None
        claim = self.claims.get(tag)
        if claim is not None and claim.expires_at <= self.now():
            self.claims.pop(tag, None)
            return None
        return claim

    def request_ownership(
        self,
        unit_or_tag: Any,
        owner: str,
        priority: CommandPriority | int,
        duration: Optional[float] = None,
        reason: str = "",
        action: str = "",
        target: str = "",
    ) -> CommandIssue:
        tag = self._tag(unit_or_tag)
        if tag is None:
            return CommandIssue(False, "invalid unit tag", owner=str(owner), priority=int(priority))

        self.frame_requests += 1
        now = self.now()
        prio = int(priority)
        owner = str(owner or "unknown")
        duration = self.default_claim_seconds if duration is None else float(duration)
        old = self.current_claim(tag)

        if old is None or old.owner == owner or prio >= int(old.priority):
            if old is not None and old.owner != owner and prio > int(old.priority):
                self.frame_preemptions += 1
                self.total_preemptions += 1
            self.claims[tag] = UnitClaim(
                tag=tag,
                owner=owner,
                priority=prio,
                expires_at=now + max(0.05, duration),
                reason=str(reason or ""),
                action=str(action or ""),
                target=str(target or ""),
                issued_at=now,
            )
            return CommandIssue(
                True,
                "granted",
                owner=owner,
                priority=prio,
                previous_owner=old.owner if old else "",
                previous_priority=int(old.priority) if old else 0,
            )

        self.frame_blocked += 1
        self.total_blocked += 1
        self.owner_block_count[owner] = self.owner_block_count.get(owner, 0) + 1
        return CommandIssue(
            False,
            f"blocked by {old.owner}(prio={old.priority}, action={old.action})",
            owner=owner,
            priority=prio,
            previous_owner=old.owner,
            previous_priority=int(old.priority),
        )

    def release(self, unit_or_tag: Any, owner: Optional[str] = None) -> bool:
        tag = self._tag(unit_or_tag)
        if tag is None:
            return False
        claim = self.current_claim(tag)
        if claim is None:
            return False
        if owner is not None and claim.owner != str(owner):
            return False
        self.claims.pop(tag, None)
        return True

    def release_owner(self, owner: str) -> int:
        owner = str(owner)
        tags = [tag for tag, claim in self.claims.items() if claim.owner == owner]
        for tag in tags:
            self.claims.pop(tag, None)
        return len(tags)

    def can_command(self, unit, owner: str, priority: CommandPriority | int) -> bool:
        claim = self.current_claim(unit)
        if claim is None or claim.owner == str(owner):
            return True
        return int(priority) >= int(claim.priority)

    # -----------------------------------------------------------------------------------------
    # Special-unit reserve
    # -----------------------------------------------------------------------------------------
    def _protected_type_ids(self) -> set:
        if UnitTypeId is None:
            return set()
        out = set()
        for name in self.DEFAULT_PROTECTED_TYPE_NAMES:
            value = getattr(UnitTypeId, name, None)
            if value is not None:
                out.add(value)
        return out

    def reserve_special_units(self) -> int:
        """Reserve fragile spell units from generic army A-move/rally.

        This is deliberately conservative: protected high-value units are reserved
        from generic rally/A-move, while defense/retreat and their own dedicated
        controllers can still preempt the reserve. Ravagers are not reserved long-term;
        they are only briefly claimed when casting bile.
        """
        ids = self._protected_type_ids()
        if not ids:
            return 0
        count = 0
        try:
            units = self.bot.units.ready.filter(lambda u: u.type_id in ids)
        except Exception:
            return 0
        for u in units:
            # Defense/retreat can still preempt this reserve, while generic rally/attack cannot.
            res = self.request_ownership(
                u,
                owner="SpecialUnitReserve",
                priority=CommandPriority.SPECIAL_RESERVE,
                duration=self.special_reserve_seconds,
                reason="protect fragile spellcaster/burrowed unit from generic army command",
                action="RESERVE_SPECIAL_UNIT",
            )
            if res.ok:
                count += 1
        return count

    # -----------------------------------------------------------------------------------------
    # Command issuing
    # -----------------------------------------------------------------------------------------
    def _already_has_action_this_frame(self, unit) -> bool:
        try:
            return int(unit.tag) in getattr(self.bot, "unit_tags_received_action", set())
        except Exception:
            return False

    def issue_move(
        self,
        unit,
        target,
        owner: str,
        priority: CommandPriority | int,
        duration: Optional[float] = None,
        reason: str = "",
    ) -> bool:
        if self._already_has_action_this_frame(unit):
            return False
        res = self.request_ownership(unit, owner, priority, duration=duration, reason=reason, action="MOVE", target=str(target))
        if not res.ok:
            return False
        try:
            unit.move(target)
            self._mark_issued(owner)
            return True
        except Exception:
            self.release(unit, owner=owner)
            return False

    def issue_attack(
        self,
        unit,
        target,
        owner: str,
        priority: CommandPriority | int,
        duration: Optional[float] = None,
        reason: str = "",
    ) -> bool:
        if self._already_has_action_this_frame(unit):
            return False
        res = self.request_ownership(unit, owner, priority, duration=duration, reason=reason, action="ATTACK", target=str(target))
        if not res.ok:
            return False
        try:
            unit.attack(target)
            self._mark_issued(owner)
            return True
        except Exception:
            self.release(unit, owner=owner)
            return False

    def issue_hold(
        self,
        unit,
        owner: str,
        priority: CommandPriority | int,
        duration: Optional[float] = None,
        reason: str = "",
    ) -> bool:
        if self._already_has_action_this_frame(unit):
            return False
        res = self.request_ownership(unit, owner, priority, duration=duration, reason=reason, action="HOLD")
        if not res.ok:
            return False
        try:
            unit.hold_position()
            self._mark_issued(owner)
            return True
        except Exception:
            self.release(unit, owner=owner)
            return False

    def issue_ability(
        self,
        unit,
        ability,
        target=None,
        owner: str = "SpellController",
        priority: CommandPriority | int = CommandPriority.SPELLCAST,
        duration: Optional[float] = 4.0,
        reason: str = "",
    ) -> bool:
        if self._already_has_action_this_frame(unit):
            return False
        ability_name = getattr(ability, "name", str(ability))
        target_text = "" if target is None else str(target)
        res = self.request_ownership(unit, owner, priority, duration=duration, reason=reason, action=ability_name, target=target_text)
        if not res.ok:
            return False
        try:
            if target is None:
                unit(ability)
            else:
                unit(ability, target)
            self._mark_issued(owner)
            return True
        except Exception:
            self.release(unit, owner=owner)
            return False

    def _mark_issued(self, owner: str) -> None:
        owner = str(owner)
        self.frame_issued += 1
        self.total_issued += 1
        self.owner_issue_count[owner] = self.owner_issue_count.get(owner, 0) + 1

    def active_summary(self) -> dict:
        self.cleanup_expired()
        by_owner: Dict[str, int] = {}
        by_action: Dict[str, int] = {}
        for claim in self.claims.values():
            by_owner[claim.owner] = by_owner.get(claim.owner, 0) + 1
            if claim.action:
                by_action[claim.action] = by_action.get(claim.action, 0) + 1
        return {
            "active_claims": len(self.claims),
            "active_by_owner": by_owner,
            "active_by_action": by_action,
            "frame_issued": self.frame_issued,
            "frame_blocked": self.frame_blocked,
            "frame_preemptions": self.frame_preemptions,
            "total_issued": self.total_issued,
            "total_blocked": self.total_blocked,
            "total_preemptions": self.total_preemptions,
        }


# Small helper for migrated code paths.  It keeps old code robust: if the RL wrapper
# does not attach a coordinator, commands fall back to direct python-sc2 orders.
def get_combat_coordinator(bot) -> Optional[CombatCoordinator]:
    coord = getattr(bot, "combat_coordinator", None)
    return coord if coord is not None else None
