from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from ares import AresBot
from sc2.data import ActionResult
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from ..action import Action
from .component import Component

if TYPE_CHECKING:
    pass


class ScoutModule(Component):

    scout_enemy_natural: bool = False
    blocked_positions: dict[Point2, float] = dict()
    static_targets: list[Point2] = list()

    def detect_blocked_bases(self) -> None:
        for error in self.state.action_errors:
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                if unit := self.unit_tag_dict.get(error.unit_tag):
                    self.blocked_positions[unit.position] = self.time

    def reset_blocked_bases(self) -> None:
        for position, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < self.time:
                del self.blocked_positions[position]

    def initialize_scout_targets(self) -> None:
        for base in self.resource_manager.bases[1 : len(self.resource_manager.bases) // 2]:
            self.static_targets.append(base.position)

        self.static_targets.sort(key=lambda t: t.distance_to(self.start_location))

        for pos in self.enemy_start_locations:
            pos = 0.5 * (pos + self.start_location)
            self.static_targets.insert(1, pos)

    def do_scouting(self) -> Iterable[Action]:

        scouts = self.units({UnitTypeId.OVERLORD, UnitTypeId.OVERSEER})
        detectors = [u for u in scouts if u.is_detector]
        nondetectors = [u for u in scouts if not u.is_detector]
        scout_targets = []
        if self.scout_enemy_natural and self.time < 3 * 60:
            target = self.resource_manager.bases[-2].position
            scout_targets.append(target)
        scout_targets.extend(self.static_targets)

        self.reset_blocked_bases()
        self.detect_blocked_bases()

        detectors.sort(key=lambda u: u.tag)
        nondetectors.sort(key=lambda u: u.tag)
        scout_targets.sort(key=lambda p: p.distance_to(self.start_location))
        for unit, target in zip(detectors, self.blocked_positions):
            yield ScoutAction(unit, target)
        for unit, target in zip(nondetectors, scout_targets):
            yield ScoutAction(unit, target)


@dataclass
class ScoutAction(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: AresBot) -> bool:
        if self.target:
            max_distance = self.unit.radius + self.unit.sight_range
            # max_distance = 1.0
            if self.target.distance_to(self.unit) < max_distance:
                return self.unit.hold_position()
            else:
                return self.unit.move(self.target)
        else:
            return False