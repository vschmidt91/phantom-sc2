from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter

from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST, HALF
from phantom.common.utils import circle, circle_perimeter, line

if TYPE_CHECKING:
    from phantom.main import PhantomBot

TUMOR_RANGE = 10
TUMOR_COOLDOWN = 304
BASE_SIZE = (5, 5)
ALL_TUMORS = {UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMOR}


class CreepState:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.tumor_active_on_game_loop = dict[int, int]()
        self.active_tumors = set[int]()
        self.placement_map = np.zeros(bot.game_info.map_size)
        self.value_map = np.zeros_like(self.placement_map)

    def _update(self, mask: np.ndarray) -> None:
        creep_grid = self.bot.mediator.get_creep_grid.T == 1
        pathing_grid = self.bot.mediator.get_ground_grid < np.inf
        self.placement_map = creep_grid & self.bot.visibility_grid & pathing_grid & mask
        value_map = np.where(~creep_grid & pathing_grid, 1.0, 0.0)
        size = BASE_SIZE
        for b in self.bot.bases:
            i0 = b[0] - size[0] // 2
            j0 = b[1] - size[1] // 2
            i1 = i0 + size[0]
            j1 = j0 + size[1]
            self.placement_map[i0:i1, j0:j1] = False
            value_map[i0:i1, j0:j1] *= 3
        self.value_map = gaussian_filter(value_map, 3) * np.where(pathing_grid, 1.0, 0.0)

    @property
    def unspread_tumor_count(self):
        return len(self.active_tumors)

    def on_tumor_spread(self, tags: Iterable[int]) -> None:
        self.active_tumors.difference_update(tags)

    def on_tumor_completed(self, tumor: Unit, spread_by_queen: bool) -> None:
        self.tumor_active_on_game_loop[tumor.tag] = self.bot.state.game_loop + TUMOR_COOLDOWN

    def step(self, mask: np.ndarray) -> "CreepAction":
        game_loop = self.bot.state.game_loop
        if self.bot.actual_iteration % 10 == 0:
            self._update(mask)

        # find tumors becoming active
        for tag, active_on_game_loop in list(self.tumor_active_on_game_loop.items()):
            if active_on_game_loop <= game_loop:
                del self.tumor_active_on_game_loop[tag]
                self.active_tumors.add(tag)

        active_tumors = list[Unit]()
        for tag in list(self.active_tumors):
            if tumor := self.bot.unit_tag_dict.get(tag):
                active_tumors.append(tumor)
            else:
                # tumor was destroyed
                self.active_tumors.remove(tag)

        return CreepAction(
            self.placement_map,
            self.value_map,
            active_tumors,
        )


@dataclass
class CreepAction:
    placement_map: np.ndarray
    value_map: np.ndarray
    active_tumors: Sequence[Unit]

    def _place_tumor(self, unit: Unit, r: int, full_circle=False) -> Action | None:
        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        circle_fn = circle if full_circle else circle_perimeter
        targets = circle_fn(x0, y0, r, shape=self.placement_map.shape)
        if not any(targets):
            return None

        target = max(targets, key=lambda t: self.value_map[t])

        if unit.is_structure:
            target = unit.position.towards(Point2(target), TUMOR_RANGE).rounded

        advance = line(target[0], target[1], x0, y0)
        for p in advance:
            if self.placement_map[p]:
                target_point = Point2(p).offset(HALF)
                return UseAbility(AbilityId.BUILD_CREEPTUMOR, target_point)

        return None

    def spread_active_tumors(self) -> Mapping[Unit, Action]:
        return {tumor: action for tumor in self.active_tumors if (action := self._place_tumor(tumor, 10))}

    def spread_with_queen(self, queen: Unit) -> Action | None:
        if 10 + ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN] <= queen.energy:
            return self._place_tumor(queen, 12, full_circle=True)
        return None
