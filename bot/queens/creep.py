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

from bot.combat.main import Combat
from bot.common.action import Action, UseAbility
from bot.common.constants import ENERGY_COST
from bot.common.main import BotBase
from bot.common.utils import circle, circle_perimeter, line, rectangle
from common.assignment import Assignment
from common.observation import Observation

TUMOR_RANGE = 10
_TUMOR_COOLDOWN = 304
_BASE_SIZE = (5, 5)


@dataclass(frozen=True)
class CreepSpreadStep:
    obs: Observation
    mask: np.ndarray

    @property
    def prevent_blocking(self):
        return self.obs.bases

    @property
    def reward_blocking(self):
        return self.obs.bases

    @cached_property
    def placement_map(self) -> np.ndarray:
        m = self.obs.creep & self.obs.visibility & self.obs.pathing & self.mask
        for b in self.prevent_blocking:
            x, y = (Point2(b) - 0.5 * Point2(_BASE_SIZE)).rounded
            r = rectangle((x, y), extent=_BASE_SIZE, shape=self.obs.creep.shape)
            m[r] = False
        return m

    @cached_property
    def value_map(self) -> np.ndarray:
        m = (~self.obs.creep & self.obs.pathing).astype(float)
        for b in self.reward_blocking:
            x, y = (Point2(b) - 0.5 * Point2(_BASE_SIZE)).rounded
            r = rectangle((x, y), extent=_BASE_SIZE, shape=self.obs.creep.shape)
            m[r] *= 3
        return m

    @cached_property
    def value_map_blurred(self) -> np.ndarray:
        return gaussian_filter(self.value_map, 3) * self.obs.pathing.astype(float)

    def _place_tumor(self, unit: Unit, r: int, full_circle=False) -> Action | None:

        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        circle_fn = circle if full_circle else circle_perimeter
        targets = circle_fn(x0, y0, r, shape=self.obs.creep.shape)
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

    def spread_with_queen(self, queen: Unit) -> Action | None:
        if queen.energy < ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN]:
            return None
        return self._place_tumor(queen, 12, full_circle=True)

    def spread_with_tumor(self, tumor: Unit) -> Action | None:
        return self._place_tumor(tumor, 10)


class CreepSpread:

    created_at_step: dict[int, int] = dict()
    spread_at_step: dict[int, int] = dict()

    @property
    def active_tumor_count(self):
        return len(self.created_at_step) - len(self.spread_at_step)

    def is_active(self, obs: Observation, tumor: Unit) -> bool:
        if not (creation_step := self.created_at_step.get(tumor.tag)):
            return False
        if tumor.tag in self.spread_at_step:
            return False
        if obs.game_loop < creation_step + _TUMOR_COOLDOWN:
            return False
        else:
            return True

    def step(self, obs: Observation, mask: np.ndarray) -> CreepSpreadStep:

        for t in set(self.created_at_step) - set(self.spread_at_step):
            if cmd := obs.unit_commands.get(t):
                if cmd.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
                    self.spread_at_step[t] = obs.game_loop

        tumors = obs.units({UnitTypeId.CREEPTUMORBURROWED})
        for tumor in tumors:
            self.created_at_step.setdefault(tumor.tag, obs.game_loop)

        return CreepSpreadStep(
            obs,
            mask,
        )
