from __future__ import annotations

from typing import Iterable

import numpy as np
from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter
from skimage.draw import circle_perimeter, line, rectangle

from ..action import Action, UseAbility
from ..constants import ENERGY_COST
from .component import Component

TUMOR_RANGE = 10


class CreepSpread(Component):
    _tumor_created_at_step: dict[int, int] = dict()
    _tumor_spread_at_step: dict[int, int] = dict()

    @property
    def active_tumor_count(self):
        return sum(1 for tag, step in self._tumor_created_at_step.items() if tag not in self._tumor_spread_at_step)

    def spread_creep(self) -> Iterable[Action]:

        self.creep_placement_map = (
            (self.state.creep.data_numpy.T == 1)
            & (self.state.visibility.data_numpy.T == 2)
            & (self.game_info.pathing_grid.data_numpy.T == 1)
        )
        self.creep_value_map = (
            (self.state.creep.data_numpy.T == 0) & (self.game_info.pathing_grid.data_numpy.T == 1)
        ).astype(float)

        def convert_rect_coords(coords: np.ndarray):
            return coords[0].astype(int).flatten(), coords[1].astype(int).flatten()

        base_size = Point2((5, 5))
        for base in self.expansion_locations_list:
            r = convert_rect_coords(
                rectangle(base.position - 0.5 * base_size, extent=base_size, shape=self.game_info.map_size)
            )
            self.creep_placement_map[r] = False
            self.creep_value_map[r] *= 3

        self.creep_value_map_blurred = gaussian_filter(self.creep_value_map, 3)

        for error in self.state.action_errors:
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                self._tumor_spread_at_step.pop(error.unit_tag, None)

        for tumor in self.mediator.get_own_structures_dict[UnitTypeId.CREEPTUMORBURROWED]:
            creation_step = self._tumor_created_at_step.setdefault(tumor.tag, self.state.game_loop)
            if self.state.game_loop >= creation_step + 304 and tumor.tag not in self._tumor_spread_at_step:
                if action := self.place_tumor(tumor):
                    yield action
                    self._tumor_spread_at_step[tumor.tag] = self.state.game_loop

        queens = self.mediator.get_own_army_dict[UnitTypeId.QUEEN]
        if self.active_tumor_count + self.townhalls.amount < len(queens):
            for queen in queens:
                if queen.energy >= ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN] and not queen.is_using_ability(
                    AbilityId.EFFECT_INJECTLARVA
                ):
                    if action := self.place_tumor(queen):
                        yield action
                    # yield UseAbility(queen, AbilityId.BUILD_CREEPTUMOR_QUEEN, queen.position)

    def place_tumor(self, unit: Unit) -> Action | None:

        origin = unit.position.rounded

        def target_value(t):
            return self.creep_value_map_blurred[t] + 1e-3 * self.start_location.distance_to(Point2(t))

        targets_x, target_y = circle_perimeter(origin[0], origin[1], TUMOR_RANGE, shape=self.game_info.map_size)
        if not any(targets_x):
            return None

        target: tuple[int, int] = max(list(zip(targets_x, target_y)), key=target_value)

        if target:
            if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
                target = origin.towards(Point2(target), TUMOR_RANGE).rounded

            line_x, line_y = line(target[0], target[1], origin[0], origin[1])
            for x, y in zip(line_x, line_y):
                if self.creep_placement_map[x, y]:
                    target = Point2((x + 0.5, y + 0.5))
                    return UseAbility(unit, AbilityId.BUILD_CREEPTUMOR, target)

        logger.debug("No creep tumor placement found.")
        return None
