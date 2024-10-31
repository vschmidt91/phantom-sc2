from abc import ABC
from typing import Iterable

import numpy as np
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter
from skimage.draw import circle_perimeter, line, rectangle

from ..action import Action, UseAbility
from ..constants import ENERGY_COST
from .base import Component

TUMOR_RANGE = 10
_TUMOR_COOLDOWN = 304


class CreepSpread(Component, ABC):
    _tumor_created_at_step: dict[int, int] = dict()
    _tumor_spread_at_step: dict[int, int] = dict()
    _creep_placement_map: np.ndarray
    _creep_value_map: np.ndarray

    @property
    def active_tumor_count(self):
        return len(self._tumor_created_at_step) - len(self._tumor_spread_at_step)

    def spread_tumors(self) -> Iterable[Action]:
        for tag, creation_step in list(self._tumor_created_at_step.items()):
            if tag in self._tumor_spread_at_step:
                pass
            elif not (tumor := self.unit_tag_dict.get(tag)):
                self._tumor_created_at_step.pop(tag, None)
            elif self.state.game_loop < creation_step + _TUMOR_COOLDOWN:
                pass
            elif action := self.place_tumor(tumor):
                yield action

    def spread_creep_with_queen(self, queen: Unit) -> Action | None:
        if queen.energy < ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN]:
            return None
        return self.place_tumor(queen)

    def place_tumor(self, unit: Unit) -> Action | None:

        origin = unit.position.rounded

        targets_x, target_y = circle_perimeter(origin[0], origin[1], TUMOR_RANGE, shape=self._creep_value_map.shape)
        if not any(targets_x):
            return None

        target: tuple[int, int] = max(list(zip(targets_x, target_y)), key=lambda p: self._creep_value_map[p])

        if target:
            if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
                target = origin.towards(Point2(target), TUMOR_RANGE).rounded

            line_x, line_y = line(target[0], target[1], origin[0], origin[1])
            for x, y in zip(line_x, line_y):
                if self._creep_placement_map[x, y]:
                    target = Point2((x + 0.5, y + 0.5))
                    return UseAbility(unit, AbilityId.BUILD_CREEPTUMOR, target)

        logger.debug("No creep tumor placement found.")
        return None

    def spread_creep(self) -> None:

        for action in self.state.actions_unit_commands:
            if action.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
                for tag in action.unit_tags:
                    self._tumor_spread_at_step[tag] = self.state.game_loop

        creep_placement_map = (
            (self.state.creep.data_numpy.T == 1)
            & (self.state.visibility.data_numpy.T == 2)
            & (self.game_info.pathing_grid.data_numpy.T == 1)
        )
        creep_value_map = (
            (self.state.creep.data_numpy.T == 0) & (self.game_info.pathing_grid.data_numpy.T == 1)
        ).astype(float)

        def convert_rect_coords(coords: np.ndarray):
            return coords[0].astype(int).flatten(), coords[1].astype(int).flatten()

        base_size = Point2((5, 5))
        for base in self.expansion_locations_list:
            r = convert_rect_coords(
                rectangle(base.position - 0.5 * base_size, extent=base_size, shape=self.game_info.map_size)
            )
            creep_placement_map[r] = False
            creep_value_map[r] *= 3

        creep_value_map_blurred = gaussian_filter(creep_value_map, 3)

        self._creep_placement_map = creep_placement_map
        self._creep_value_map = creep_value_map_blurred

        for tumor in self.mediator.get_own_structures_dict[UnitTypeId.CREEPTUMORBURROWED]:
            self._tumor_created_at_step.setdefault(tumor.tag, self.state.game_loop)

        #     if self.state.game_loop >= creation_step + 304 and tumor.tag not in self._tumor_spread_at_step:
        #         if action := self.place_tumor(tumor):
        #             yield action
        # self._tumor_spread_at_step[tumor.tag] = self.state.game_loop
