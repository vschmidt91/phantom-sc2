from dataclasses import dataclass
from functools import cached_property
from typing import Iterable

import numpy as np
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter

from bot.action import Action, UseAbility
from bot.base import BotBase
from bot.constants import ENERGY_COST
from bot.utils import circle_perimeter, line, rectangle

TUMOR_RANGE = 10
_TUMOR_COOLDOWN = 304
_BASE_SIZE = (5, 5)


@dataclass(frozen=True)
class CreepSpreadContext:
    context: BotBase
    creep: np.ndarray
    visibility: np.ndarray
    pathing: np.ndarray
    prevent_blocking: set[Point2]
    reward_blocking: set[Point2]
    game_loop: int

    @cached_property
    def placement_map(self) -> np.ndarray:
        m = self.creep & self.visibility & self.pathing
        for b in self.prevent_blocking:
            x, y = (Point2(b) - 0.5 * Point2(_BASE_SIZE)).rounded
            r = rectangle((x, y), extent=_BASE_SIZE, shape=self.creep.shape)
            m[r] = False
        return m

    @cached_property
    def value_map(self) -> np.ndarray:
        m = (~self.creep & self.pathing).astype(float)
        for b in self.reward_blocking:
            x, y = (Point2(b) - 0.5 * Point2(_BASE_SIZE)).rounded
            r = rectangle((x, y), extent=_BASE_SIZE, shape=self.creep.shape)
            m[r] *= 3
        return m

    @cached_property
    def value_map_blurred(self) -> np.ndarray:
        return gaussian_filter(self.value_map, 3)

    def place_tumor(self, unit: Unit) -> Action | None:

        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        targets = circle_perimeter(x0, y0, TUMOR_RANGE, shape=self.creep.shape)
        if not any(targets):
            return None

        target = max(targets, key=lambda t: self.value_map_blurred[t])

        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            target = unit.position.towards(Point2(target), TUMOR_RANGE).rounded

        advance = line(target[0], target[1], x0, y0)
        for p in advance:
            if self.placement_map[p]:
                target_point = Point2(p).offset(Point2((0.5, 0.5)))
                return UseAbility(unit, AbilityId.BUILD_CREEPTUMOR, target_point)

        logger.debug("No creep tumor placement found.")
        return None

    def spread_creep_with_queen(self, queen: Unit) -> Action | None:
        if queen.energy < ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN]:
            return None
        return self.place_tumor(queen)


class CreepSpread:

    _tumor_created_at_step: dict[int, int] = dict()
    _tumor_spread_at_step: dict[int, int] = dict()

    @property
    def active_tumor_count(self):
        return len(self._tumor_created_at_step) - len(self._tumor_spread_at_step)

    def get_active_tumors(self, context: BotBase) -> Iterable[Unit]:
        for tag, creation_step in list(self._tumor_created_at_step.items()):
            if tag in self._tumor_spread_at_step:
                pass
            elif context.state.game_loop < creation_step + _TUMOR_COOLDOWN:
                pass
            elif not (tumor := context.unit_tag_dict.get(tag)):
                self._tumor_created_at_step.pop(tag, None)
            else:
                yield tumor

    def update(self, context: BotBase) -> CreepSpreadContext:
        for action in context.state.actions_unit_commands:
            if action.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
                for tag in action.unit_tags:
                    self._tumor_spread_at_step[tag] = context.state.game_loop

        for tumor in context.mediator.get_own_structures_dict[UnitTypeId.CREEPTUMORBURROWED]:
            self._tumor_created_at_step.setdefault(tumor.tag, context.state.game_loop)

        creep = context.state.creep.data_numpy.T == 1
        visibility = context.state.visibility.data_numpy.T == 2
        pathing = context.game_info.pathing_grid.data_numpy.T == 1
        bases = {b.position for b in context.bases}

        return CreepSpreadContext(
            context,
            creep,
            visibility,
            pathing,
            prevent_blocking=bases,
            reward_blocking=bases,
            game_loop=context.state.game_loop,
        )