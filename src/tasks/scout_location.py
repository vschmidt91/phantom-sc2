from typing import Optional

from task import Task

from sc2.position import Point2
from sc2.unit import UnitCommand

from ..units.unit import AIUnit


class ScoutLocationTask(Task):
    def __init__(self) -> None:
        self.target: Point2

    def get_command(self, unit: AIUnit) -> Optional[UnitCommand]:
        max_distance = unit.state.radius + unit.state.sight_range
        if max_distance < self.target.distance_to(unit.state.position):
            move_to = self.target.towards(unit.state, max_distance)
            return unit.state.move(move_to)
        else:
            return None
