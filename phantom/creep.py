from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger
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

BASE_SIZE = (5, 5)


class CreepSpread:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.placement_map = np.zeros(bot.game_info.map_size)
        self.value_map = np.zeros_like(self.placement_map)
        self.update_interval = 10

    def on_step(self) -> None:
        if self.bot.actual_iteration % self.update_interval == 0:
            self._update_maps()

    def spread_with(self, unit: Unit) -> Action | None:
        if unit.type_id == UnitTypeId.QUEEN:
            if 10 + ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN] <= unit.energy:
                return self._place_tumor(unit, 12, full_circle=True)
        elif unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            return self._place_tumor(unit, 10)
        return None

    def _update_maps(self) -> None:
        creep_grid = self.bot.mediator.get_creep_grid.T == 1
        pathing_grid = self.bot.mediator.get_cached_ground_grid == 1.0
        safety_grid = self.bot.mediator.get_ground_grid == 1.0
        self.placement_map = creep_grid & self.bot.visibility_grid & safety_grid
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

    def _place_tumor(self, unit: Unit, r: int, full_circle=False) -> Action | None:
        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        circle_fn = circle if full_circle else circle_perimeter
        targets = circle_fn(x0, y0, r, shape=self.placement_map.shape)
        if not any(targets):
            return None

        target = max(targets, key=lambda t: self.value_map[t])

        if unit.is_structure:
            target = unit.position.towards(Point2(target), r).rounded

        advance = line(target[0], target[1], x0, y0)
        for p in advance:
            if self.placement_map[p]:
                target_point = Point2(p).offset(HALF)
                return UseAbility(AbilityId.BUILD_CREEPTUMOR, target_point)

        return None


class CreepTumors:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.tumor_created_at = dict[int, int]()
        self.tumor_active_since = dict[int, int]()
        self.tumor_stuck_game_loops = 3000  # remove the tumor if it fails to spread longer than this
        self.tumor_cooldown = 304

    @property
    def unspread_tumor_count(self):
        return len(self.tumor_active_since) + len(self.tumor_created_at)

    @property
    def active_tumors(self) -> Sequence[Unit]:
        return [self.bot.unit_tag_dict[t] for t in self.tumor_active_since]

    def on_tumor_completed(self, tumor: Unit, spread_by_queen: bool) -> None:
        self.tumor_created_at[tumor.tag] = self.bot.state.game_loop

    def on_step(self) -> None:
        game_loop = self.bot.state.game_loop

        for action in self.bot.actions_by_ability[AbilityId.BUILD_CREEPTUMOR_TUMOR]:
            for tag in action.unit_tags:
                # the tumor might already be marked as stuck if the spread order got delayed due to the APM limit
                self.tumor_active_since.pop(tag, None)

        # find tumors becoming active
        for tag, created_at in list(self.tumor_created_at.items()):
            if tag not in self.bot.unit_tag_dict:
                del self.tumor_created_at[tag]
            elif created_at + self.tumor_cooldown <= game_loop:
                del self.tumor_created_at[tag]
                self.tumor_active_since[tag] = game_loop

        active_tumors = list[Unit]()
        for tag, active_since in list(self.tumor_active_since.items()):
            if active_since + self.tumor_stuck_game_loops <= game_loop:
                logger.info(f"tumor with {tag=} failed to spread for {self.tumor_stuck_game_loops} loops")
                del self.tumor_active_since[tag]
            elif tumor := self.bot.unit_tag_dict.get(tag):
                active_tumors.append(tumor)
            else:
                del self.tumor_active_since[tag]
