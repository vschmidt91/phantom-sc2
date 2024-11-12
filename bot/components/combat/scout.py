from dataclasses import dataclass
from typing import Iterable

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.common.action import Action
from bot.common.base import BotBase


@dataclass
class ScoutAction(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        if self.unit.distance_to(self.target) < self.unit.radius + self.unit.sight_range:
            return self.unit.hold_position()
        else:
            return self.unit.move(self.target)


class Scout:

    scout_enemy_natural: bool = False
    static_targets: list[Point2] = list()

    def initialize_scout_targets(self, context: BotBase, bases: list[Point2]) -> None:
        for base in bases[1 : len(bases) // 2]:
            self.static_targets.append(base.position)

        self.static_targets.sort(key=lambda t: t.distance_to(context.start_location))

        for pos in context.enemy_start_locations:
            pos = 0.5 * (pos + context.start_location)
            self.static_targets.insert(1, pos)

    def get_actions(
        self, context: BotBase, scouts: Units, blocked_positions: Iterable[Point2]
    ) -> Iterable[ScoutAction]:

        detectors = [u for u in scouts if u.is_detector]
        non_detectors = [u for u in scouts if not u.is_detector]
        scout_targets = []
        if self.scout_enemy_natural and context.time < 3 * 60:
            target = context.expansion_locations_list[-2]
            scout_targets.append(target)
        scout_targets.extend(self.static_targets)

        # self.reset_blocked_bases()
        # self.detect_blocked_bases()

        detectors.sort(key=lambda u: u.tag)
        non_detectors.sort(key=lambda u: u.tag)
        scout_targets.sort(key=lambda p: p.distance_to(context.start_location))
        for unit, target in zip(detectors, blocked_positions):
            yield ScoutAction(unit, target)
        for unit, target in zip(non_detectors, scout_targets):
            yield ScoutAction(unit, target)
