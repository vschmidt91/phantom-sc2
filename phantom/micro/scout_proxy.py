from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from cython_extensions import cy_distance_to
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Move
from phantom.common.point import to_point

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.micro.combat import CombatSituation
    from phantom.observation import Observation


class ScoutProxy:
    def __init__(
        self,
        bot: PhantomBot,
        samples_max: int = 24,
    ) -> None:
        self.bot = bot
        self._situation: CombatSituation | None = None
        self._scout_tags = tuple[int, ...]()
        self._target_by_scout_tag = dict[int, Point2]()
        self._samples_max = max(1, samples_max)
        self._rng = np.random.default_rng()
        self._vision_age = np.full(self.bot.game_info.map_size, -1, dtype=np.int32)
        self._ground_mask = np.isfinite(self.bot.clean_ground_grid)
        if self._ground_mask.shape != self._vision_age.shape:
            self._ground_mask = np.ones(self._vision_age.shape, dtype=bool)
        self._priority_target = self.bot.mediator.get_own_nat

    def on_step(self, observation: Observation) -> None:
        self._situation = observation.combat
        self._scout_tags = observation.scout_proxy_overlord_tags
        self._drop_visible_targets()
        self._update_vision_age_grid()

    def __call__(self, unit: Unit) -> Action | None:
        if self._situation is not None and (action := self._situation.keep_unit_safe(unit)):
            return action
        target = self._target_by_scout_tag.get(unit.tag)
        if target is None:
            target = self._pick_target_for(unit)
            if target is None:
                return None
            self._target_by_scout_tag[unit.tag] = target
        if unit.is_idle or unit.distance_to(target) > 1.5:
            return Move(target)
        return None

    def _drop_visible_targets(self) -> None:
        for scout_tag, target in list(self._target_by_scout_tag.items()):
            target_point = to_point(target)
            if not self._in_bounds(target_point) or self.bot.is_visible(Point2(target_point)):
                self._target_by_scout_tag.pop(scout_tag, None)

    def _update_vision_age_grid(self) -> None:
        visible = np.asarray(self.bot.state.visibility.data_numpy.T) == 2
        self._vision_age[visible] = self.bot.state.game_loop

    def _pick_target_for(self, scout: Unit) -> Point2 | None:
        best_tile: tuple[int, int] | None = None
        best_age = float("inf")
        best_nat_distance = float("inf")
        center = scout.position
        sight_range = scout.radius + scout.sight_range
        radius_coeff = 1.0 / scout.movement_speed
        for radius in np.linspace(sight_range, sight_range + self._samples_max, self._samples_max):
            angle = self._rng.uniform(0, 2 * np.pi)
            tile = to_point(center + radius * Point2((np.cos(angle), np.sin(angle))))
            if self._is_candidate(tile):
                age = self._vision_age[tile]
                nat_distance = cy_distance_to(Point2(tile), self._priority_target)
                if (
                    best_tile is None
                    or age + radius * radius_coeff < best_age
                    or (age == best_age and nat_distance < best_nat_distance)
                ):
                    best_age = age
                    best_nat_distance = nat_distance
                    best_tile = tile
        return Point2(best_tile) if best_tile is not None else None

    def _is_candidate(self, tile: tuple[int, int]) -> bool:
        if not self._in_bounds(tile):
            return False
        if not self._ground_mask[tile]:
            return False
        return not self.bot.is_visible(Point2(tile))

    def _clip_point(self, point: tuple[float, float] | np.ndarray) -> tuple[int, int]:
        x = int(np.clip(point[0], 0, self._vision_age.shape[0] - 1))
        y = int(np.clip(point[1], 0, self._vision_age.shape[1] - 1))
        return x, y

    def _in_bounds(self, tile: tuple[int, int]) -> bool:
        return 0 <= tile[0] < self._vision_age.shape[0] and 0 <= tile[1] < self._vision_age.shape[1]
