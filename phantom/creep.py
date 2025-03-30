from dataclasses import dataclass
from functools import cached_property

import numpy as np
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from scipy.ndimage import gaussian_filter

from phantom.common.action import Action, UseAbility
from phantom.common.constants import ENERGY_COST, HALF
from phantom.common.utils import circle, circle_perimeter, line, rectangle
from phantom.observation import Observation

TUMOR_RANGE = 10
_TUMOR_COOLDOWN = 304
_BASE_SIZE = (5, 5)


@dataclass(frozen=True)
class CreepAction:
    obs: Observation
    mask: np.ndarray
    active_tumors: set[Unit]

    @property
    def prevent_blocking(self):
        return self.obs.bases

    @property
    def reward_blocking(self):
        return self.obs.bases

    @cached_property
    def placement_map(self) -> np.ndarray:
        m = self.obs.creep & self.obs.vision & (self.obs.pathing == 1) & self.mask
        for b in self.prevent_blocking:
            x, y = (Point2(b).offset(HALF) - 0.5 * Point2(_BASE_SIZE)).rounded
            r = rectangle((x, y), extent=_BASE_SIZE, shape=self.obs.creep.shape)
            m[r] = False
        return m

    @cached_property
    def value_map(self) -> np.ndarray:
        m = (~self.obs.creep & (self.obs.pathing == 1)).astype(float)
        for b in self.reward_blocking:
            x, y = (Point2(b).offset(HALF) - 0.5 * Point2(_BASE_SIZE)).rounded
            r = rectangle((x, y), extent=_BASE_SIZE, shape=self.obs.creep.shape)
            m[r] *= 3
        return m

    @cached_property
    def value_map_blurred(self) -> np.ndarray:
        return gaussian_filter(self.value_map, 3) * (self.obs.pathing == 1).astype(float)

    def _place_tumor(self, unit: Unit, r: int, full_circle=False) -> Action | None:
        x0 = round(unit.position.x)
        y0 = round(unit.position.y)

        circle_fn = circle if full_circle else circle_perimeter
        targets = circle_fn(x0, y0, r, shape=self.obs.creep.shape)
        if not any(targets):
            return None

        target = max(targets, key=lambda t: self.value_map_blurred[t])

        if unit.is_structure:
            target = unit.position.towards(Point2(target), TUMOR_RANGE).rounded

        advance = line(target[0], target[1], x0, y0)
        for p in advance:
            if self.placement_map[p]:
                target_point = Point2(p).offset(Point2((0.5, 0.5)))
                return UseAbility(unit, AbilityId.BUILD_CREEPTUMOR, target_point)

        logger.warning("No creep tumor placement found.")
        return None

    def spread_with_queen(self, queen: Unit) -> Action | None:
        if ENERGY_COST[AbilityId.BUILD_CREEPTUMOR_QUEEN] <= queen.energy:
            return self._place_tumor(queen, 12, full_circle=True)
        return None

    def spread_with_tumor(self, tumor: Unit) -> Action | None:
        return self._place_tumor(tumor, 10)


class CreepState:
    created_at_step = dict[int, int]()
    spread_at_step = dict[int, int]()

    @property
    def unspread_tumor_count(self):
        return len(self.created_at_step) - len(self.spread_at_step)

    def step(self, obs: Observation, mask: np.ndarray) -> CreepAction:
        for t in set(self.created_at_step) - set(self.spread_at_step):
            if (cmd := obs.unit_commands.get(t)) and cmd.exact_id == AbilityId.BUILD_CREEPTUMOR_TUMOR:
                self.spread_at_step[t] = obs.game_loop

        def is_active(t: Unit) -> bool:
            creation_step = self.created_at_step.setdefault(t.tag, obs.game_loop)
            if t.tag in self.spread_at_step:
                return False
            return creation_step + _TUMOR_COOLDOWN <= obs.game_loop

        all_tumors = obs.structures({UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMOR})
        active_tumors = {t for t in all_tumors if is_active(t)}

        return CreepAction(
            obs,
            mask,
            active_tumors,
        )
