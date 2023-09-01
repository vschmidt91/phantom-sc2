from __future__ import annotations

import abc
from typing import Optional
import functools
import math

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import UnitCommand
from skimage.draw import circle_perimeter, line, disk

from ..constants import ENERGY_COST
from ..units.unit import AIUnit, Behavior

TUMOR_RANGE = 10


class CreepBehavior(Behavior):

    def __init__(self, unit: AIUnit) -> None:
        super().__init__(unit)

    @abc.abstractmethod
    def can_spread_creep(self) -> bool:
        raise NotImplementedError()

    def spread_creep(self) -> Optional[UnitCommand]:

        if not self.can_spread_creep():
            return None

        def target_value(t):
            return self.ai.creep_value_map_blurred[t]

        def distance_to_map_center(p):
            return np.linalg.norm(np.subtract(p, self.ai.game_info.map_center))

        def target_comparison(a, b):
            cmp = np.sign(target_value(a) - target_value(b))
            if cmp != 0:
                return cmp
            cmp = np.sign(distance_to_map_center(b) - distance_to_map_center(a))
            if cmp != 0:
                return cmp
            cmp = np.sign(hash(a) - hash(b))
            if cmp != 0:
                return cmp
            return 0
        target_key = functools.cmp_to_key(target_comparison)

        origin = np.array(self.unit.state.position).astype(int)
        targets = np.stack(
            disk(
                origin,
                TUMOR_RANGE,
                shape=self.ai.game_info.map_size,
            ),
            axis=-1,
        )
        targets = [tuple(t) for t in targets.tolist()]
        target = max(
            # (p for p in targets if 1 == self.ai.game_info.pathing_grid[p]),
            (p for p in targets if self.ai.creep_placement_map[p]),
            key=target_key,
            default=None,
        )

        if target:
            # for x, y in zip(*line(*target, *origin)):
            #     if self.ai.creep_placement_map[x, y]:
            #         target = Point2((x, y))
            return self.unit.state.build(UnitTypeId.CREEPTUMOR, Point2(target))

        # random mode
        # angle = np.random.uniform(0, 2 * np.pi)
        # radius = np.random.uniform(1, TUMOR_RANGE)
        # target = origin + radius * np.array([np.cos(angle), np.sin(angle)])
        # target = tuple(target.astype(int))

        # if self.ai.creep_placement_map[target]:
        #     return self.unit.state.build(UnitTypeId.CREEPTUMOR, Point2(target))

        return None
