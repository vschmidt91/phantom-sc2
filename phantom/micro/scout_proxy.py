from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from cython_extensions import cy_distance_to
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.action import Action, Move
from phantom.common.point import to_point
from phantom.common.utils import circle_perimeter

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.micro.combat import CombatStep
    from phantom.observation import Observation


class ScoutProxy:
    def __init__(
        self,
        bot: PhantomBot,
        samples_max: int = 24,
    ) -> None:
        self.bot = bot
        self._combat: CombatStep | None = None
        self._scout_tags = tuple[int, ...]()
        self._target_by_scout_tag = dict[int, Point2]()
        self._samples_max = max(1, samples_max)
        self._vision_age = np.full(self.bot.game_info.map_size, -1, dtype=np.int32)
        self._ground_mask = np.isfinite(self.bot.clean_ground_grid)
        if self._ground_mask.shape != self._vision_age.shape:
            self._ground_mask = np.ones(self._vision_age.shape, dtype=bool)

    def on_step(self, observation: Observation) -> None:
        self._combat = observation.combat
        self._scout_tags = observation.scout_proxy_overlord_tags
        self._cleanup_stale_targets()
        self._drop_visible_targets()
        self._update_vision_age_grid()

    def __call__(self, unit: Unit) -> Action | None:
        if self._combat is not None and (action := self._combat.keep_unit_safe(unit)):
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

    def _cleanup_stale_targets(self) -> None:
        if not self._target_by_scout_tag:
            return

        live_scouts = set(self._scout_tags)
        for scout_tag in list(self._target_by_scout_tag):
            if scout_tag not in live_scouts:
                self._target_by_scout_tag.pop(scout_tag, None)

    def _drop_visible_targets(self) -> None:
        if not self._target_by_scout_tag:
            return

        for scout_tag, target in list(self._target_by_scout_tag.items()):
            target_point = to_point(target)
            if not self._in_bounds(target_point) or self.bot.is_visible(Point2(target_point)):
                self._target_by_scout_tag.pop(scout_tag, None)

    def _update_vision_age_grid(self) -> None:
        visible = np.asarray(self.bot.state.visibility.data_numpy.T) == 2
        self._vision_age[visible] = self.bot.state.game_loop

    def _pick_target_for(self, scout: Unit) -> Point2 | None:
        best_tile: tuple[int, int] | None = None
        best_age = -1
        best_nat_distance = float("inf")
        best_never_seen = False
        game_loop = self.bot.state.game_loop
        center = self._clip_point((scout.position.x, scout.position.y))
        own_nat = self.bot.mediator.get_own_nat
        radius = max(1, int(np.ceil(scout.radius + scout.sight_range)))
        sampled = 0
        while sampled < self._samples_max:
            for tile in circle_perimeter(*center, r=radius, shape=self._vision_age.shape):
                sampled += 1
                if sampled > self._samples_max:
                    break
                if self._is_candidate(tile):
                    age = self._tile_age(tile, game_loop)
                    nat_distance = cy_distance_to(Point2(tile), own_nat)
                    never_seen = self._vision_age[tile] < 0
                    better = False
                    if (
                        best_tile is None
                        or (never_seen and not best_never_seen)
                        or (
                            never_seen == best_never_seen
                            and (age > best_age or (age == best_age and nat_distance < best_nat_distance))
                        )
                    ):
                        better = True
                    if not better:
                        continue
                    best_never_seen = never_seen
                    best_age = age
                    best_nat_distance = nat_distance
                    best_tile = tile
            radius += 1
        return Point2(best_tile) if best_tile is not None else None

    def _is_candidate(self, tile: tuple[int, int]) -> bool:
        if not self._in_bounds(tile):
            return False
        if not self._ground_mask[tile]:
            return False
        return not self.bot.is_visible(Point2(tile))

    def _tile_age(self, tile: tuple[int, int], game_loop: int) -> int:
        last_seen = int(self._vision_age[tile])
        return 1_000_000 + game_loop if last_seen < 0 else max(0, game_loop - last_seen)

    def _clip_point(self, point: tuple[float, float] | np.ndarray) -> tuple[int, int]:
        x = int(np.clip(point[0], 0, self._vision_age.shape[0] - 1))
        y = int(np.clip(point[1], 0, self._vision_age.shape[1] - 1))
        return x, y

    def _in_bounds(self, tile: tuple[int, int]) -> bool:
        return 0 <= tile[0] < self._vision_age.shape[0] and 0 <= tile[1] < self._vision_age.shape[1]
