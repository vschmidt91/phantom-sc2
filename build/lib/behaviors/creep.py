from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit, UnitCommand
from skimage.draw import circle_perimeter, line

from ..constants import ENERGY_COST
from ..units.unit import AIUnit

if TYPE_CHECKING:
    from ..ai_base import AIBase

TUMOR_RANGE = 10


class CreepBehavior(AIUnit):
    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.creation_step = self.ai.state.game_loop

    def spread_creep(self) -> Optional[UnitCommand]:
        if self.state.type_id == UnitTypeId.CREEPTUMORBURROWED:
            age = self.ai.state.game_loop - self.creation_step
            if age < 550:
                return None
        elif self.state.type_id == UnitTypeId.QUEEN:
            if self.state.energy < ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN]:
                return None
            elif self.state.is_using_ability(AbilityId.BUILD_CREEPTUMOR_QUEEN):
                return self.state(
                    AbilityId.BUILD_CREEPTUMOR_QUEEN, target=self.state.order_target
                )
        else:
            return None

        def target_value(t):
            return self.ai.creep_value_map_blurred[t]

        origin = np.array(self.state.position).astype(int)
        targets = np.stack(
            circle_perimeter(
                *origin,
                TUMOR_RANGE,
                shape=self.ai.game_info.map_size,
            ),
            axis=-1,
        )
        targets = [tuple(t) for t in targets.tolist()]
        target = max(
            (p for p in targets if 1 == self.ai.game_info.pathing_grid[p]),
            key=target_value,
            default=None,
        )

        if target:
            for x, y in zip(*line(*target, *origin)):
                if self.ai.creep_placement_map[x, y]:
                    target = Point2((x, y))
                    return self.state.build(UnitTypeId.CREEPTUMOR, target)

        # random mode
        angle = np.random.uniform(0, 2 * np.pi)
        radius = np.random.uniform(1, TUMOR_RANGE)
        target = origin + radius * np.array([np.cos(angle), np.sin(angle)])
        target = tuple(target.astype(int))

        if self.ai.creep_placement_map[target]:
            return self.state.build(UnitTypeId.CREEPTUMOR, Point2(target))

        return None
