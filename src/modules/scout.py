from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit_command import UnitCommand

import numpy as np

from ..units.unit import AIUnit, Behavior
from .module import AIModule


class ScoutModule(AIModule):
    def __init__(self, ai: "AIBase") -> None:
        super().__init__(ai)

        self.scout_enemy_natural: bool = False
        self.blocked_positions: Dict[Point2, float] = dict()
        self.static_targets: List[Point2] = list()

        # for base in self.ai.resource_manager.bases[
        #     1 : len(self.ai.resource_manager.bases) // 2
        # ]:
        #     self.static_targets.append(base.position)

        # self.static_targets.sort(key=lambda t: t.distance_to(self.ai.start_location))

        # for pos in self.ai.enemy_start_locations:
        #     pos = 0.5 * (pos + self.ai.start_location)
        #     self.static_targets.insert(1, pos)

    def reset_blocked_bases(self) -> None:
        for position, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < self.ai.time:
                del self.blocked_positions[position]

    def send_units(
        self, units: Iterable[ScoutBehavior], targets: Iterable[Point2]
    ) -> None:
        targets_set = set(targets)
        for scout in units:
            if scout.scout_position not in targets_set:
                scout.scout_position = None

        scouted_positions = {scout.scout_position for scout in units}
        if (
            unscouted_target := next(
                (t for t in targets if t not in scouted_positions), None
            )
        ) and (
            scout := next((s for s in units if not s.scout_position), None)
        ):
            scout.scout_position = unscouted_target

    async def on_step(self) -> None:
        scouts = list(self.ai.unit_manager.behavior_of_type(ScoutBehavior))
        detectors = [behavior for behavior in scouts if behavior.unit.state.is_detector]
        nondetectors = [
            behavior for behavior in scouts if not behavior.unit.state.is_detector
        ]
        scout_targets = []
        if self.scout_enemy_natural and self.ai.time < 3 * 60:
            target = self.ai.resource_manager.bases[-2].position
            scout_targets.append(target)
        scout_targets.extend(self.static_targets)

        self.reset_blocked_bases()
        self.send_units(detectors, self.blocked_positions.keys())
        self.send_units(nondetectors, scout_targets)


class ScoutBehavior(Behavior):
    def __init__(self, unit: AIUnit):
        super().__init__(unit)
        self.scout_position: Optional[Point2] = None

    def scout(self) -> Optional[UnitCommand]:
        # if self.unit.state.type_id == UnitTypeId.OVERSEER:
        #     return None
        if not self.scout_position:
            return None
        max_distance = self.unit.state.radius + self.unit.state.sight_range
        # max_distance = 1.0
        if self.scout_position.distance_to(self.unit.state) < max_distance:
            return self.unit.state.hold_position()
        else:
            return self.unit.state.move(self.scout_position)
