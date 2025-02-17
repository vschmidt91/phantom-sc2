from dataclasses import dataclass
from functools import cached_property

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.common.action import Action
from bot.common.main import BotBase


@dataclass
class ScoutAction(Action):
    unit: Unit
    target: Point2

    async def execute(self, bot: BotBase) -> bool:
        if self.unit.distance_to(self.target) < self.unit.radius + self.unit.sight_range:
            if self.unit.is_idle:
                return True
            return self.unit.stop()
        else:
            return self.unit.move(self.target)


@dataclass(frozen=True)
class Scout:

    context: BotBase
    units: Units
    scout_positions: frozenset[Point2]
    detect_positions: frozenset[Point2]

    @cached_property
    def detectors(self) -> list[Unit]:
        return [u for u in self.units if u.is_detector]

    @cached_property
    def nondetectors(self) -> list[Unit]:
        return [u for u in self.units if not u.is_detector]

    def get_actions(self) -> dict[Unit, ScoutAction]:
        detectors = sorted(self.detectors, key=lambda u: u.tag)
        nondetectors = sorted(self.nondetectors, key=lambda u: u.tag)
        scout_positions = sorted(self.scout_positions, key=lambda p: hash(p))
        detect_positions = sorted(self.detect_positions, key=lambda p: hash(p))

        return {unit: ScoutAction(unit, target) for unit, target in zip(detectors, detect_positions)} | {
            unit: ScoutAction(unit, target) for unit, target in zip(nondetectors, scout_positions)
        }
