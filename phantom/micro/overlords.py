from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Move, UseAbility
from phantom.micro.combat import CombatStep
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class Overlords:
    def __init__(self, bot: PhantomBot) -> None:
        self.bot = bot
        self._had_lair_tech = False
        self._known_overlords = set[int]()
        self._pending_creep_enable = set[int]()
        self._support_target_by_overlord = dict[int, Point2]()
        self._reassignment_interval = 16
        self._candidates = list[Unit]()
        self._combat: CombatStep | None = None
        self._scout_overlord_tag: int | None = None
        self._scout_proxy_overlord_tags = tuple[int, ...]()

    def on_step(self, observation: Observation) -> None:
        overlords = observation.bot.units({UnitTypeId.OVERLORD, UnitTypeId.OVERLORDTRANSPORT})
        self._scout_overlord_tag = observation.scout_overlord_tag
        self._scout_proxy_overlord_tags = observation.scout_proxy_overlord_tags
        self._combat = observation.combat
        excluded_tags = set(self._scout_proxy_overlord_tags)
        if self._scout_overlord_tag is not None:
            excluded_tags.add(self._scout_overlord_tag)
        self._candidates = [u for u in overlords if u.tag not in excluded_tags]
        if self._candidates:
            self._update_creep_enable_queue(self._candidates)

    def get_actions(self, observation: Observation) -> Mapping[Unit, Action]:
        if not self._candidates or self._combat is None:
            return {}

        actions = dict[Unit, Action]()
        movable = list[Unit]()
        for overlord in self._candidates:
            if (action := self._combat.keep_unit_safe(overlord)) or (action := self._enable_creep_with(overlord)):
                actions[overlord] = action
            else:
                movable.append(overlord)

        self._update_support_assignments(movable)
        for overlord in movable:
            if action := self._move_to_assigned_support_position(overlord):
                actions[overlord] = action

        return actions

    def _update_creep_enable_queue(self, overlords: Sequence[Unit]) -> None:
        has_lair_tech = bool(self.bot.structures({UnitTypeId.LAIR, UnitTypeId.HIVE}).ready)
        current_tags = {u.tag for u in overlords}

        if has_lair_tech and not self._had_lair_tech:
            self._pending_creep_enable.update(current_tags)

        new_tags = current_tags - self._known_overlords
        if has_lair_tech:
            self._pending_creep_enable.update(new_tags)

        self._known_overlords = current_tags
        self._had_lair_tech = has_lair_tech

    def _enable_creep_with(self, overlord: Unit) -> Action | None:
        if overlord.tag not in self._pending_creep_enable:
            return None

        abilities = getattr(overlord, "abilities", ())
        if AbilityId.BEHAVIOR_GENERATECREEPOFF in abilities:
            self._pending_creep_enable.discard(overlord.tag)
            return None

        if AbilityId.BEHAVIOR_GENERATECREEPON in abilities:
            self._pending_creep_enable.discard(overlord.tag)
            return UseAbility(AbilityId.BEHAVIOR_GENERATECREEPON)

        return None

    def _update_support_assignments(self, overlords: Sequence[Unit]) -> None:
        if not overlords:
            self._support_target_by_overlord.clear()
            return

        # force ares to keep creep edge updated
        _ = self.bot.mediator.get_creep_edges

        if self.bot.actual_iteration % self._reassignment_interval != 0 and self._support_target_by_overlord:
            return

        assignment = self.bot.mediator.get_overlord_creep_spotter_positions(
            overlords=overlords, target_pos=self.bot.mediator.get_enemy_nat
        )
        if not assignment:
            self._support_target_by_overlord.clear()
            return

        self._support_target_by_overlord = {tag: Point2(position) for tag, position in assignment.items()}

    def _move_to_assigned_support_position(self, overlord: Unit) -> Action | None:
        target = self._support_target_by_overlord.get(overlord.tag)
        if target is None:
            return None
        if overlord.distance_to(target) < 2.0 and not overlord.is_idle:
            return None

        air_grid = self.bot.mediator.get_air_grid
        if not self.bot.mediator.is_position_safe(grid=air_grid, position=target):
            return None

        move_target = self.bot.mediator.find_path_next_point(
            start=overlord.position,
            target=target,
            grid=air_grid,
            smoothing=True,
        )
        return Move(move_target)
