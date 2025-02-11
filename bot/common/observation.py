from dataclasses import dataclass
from functools import cached_property
from itertools import product

import numpy as np
from sc2.game_state import ActionRawUnitCommand
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sklearn.metrics import pairwise_distances

from bot.common.constants import CIVILIANS, ENEMY_CIVILIANS
from bot.common.main import BotBase


@dataclass(frozen=True)
class Observation:
    bot: BotBase

    @property
    def units(self) -> Units:
        if self.bot.is_micro_map:
            return self.bot.units
        else:
            return self.bot.units.exclude_type(CIVILIANS)

    @property
    def enemy_units(self) -> Units:
        if self.bot.is_micro_map:
            return self.bot.enemy_units
        else:
            return self.bot.all_enemy_units.exclude_type(ENEMY_CIVILIANS)

    @property
    def structures(self) -> Units:
        return self.bot.structures

    @property
    def enemy_structures(self) -> Units:
        return self.bot.enemy_structures

    @property
    def is_micro_map(self) -> bool:
        return self.bot.is_micro_map

    @cached_property
    def enemy_start_locations(self) -> frozenset[Point2]:
        return frozenset(self.bot.enemy_start_locations)

    @property
    def game_loop(self):
        return self.bot.state.game_loop

    @property
    def max_harvesters(self):
        return sum(
            (
                2 * self.bot.all_taken_resources.mineral_field.amount,
                3 * self.bot.all_taken_resources.vespene_geyser.amount,
            )
        )

    @cached_property
    def creep(self) -> np.ndarray:
        return self.bot.state.creep.data_numpy.T == 1

    @cached_property
    def visibility(self) -> np.ndarray:
        return self.bot.state.visibility.data_numpy.T == 2

    @cached_property
    def pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_pyastar_grid()

    @cached_property
    def air_pathing(self) -> np.ndarray:
        return self.bot.mediator.get_map_data_object.get_clean_air_grid()

    @cached_property
    def unit_commands(self) -> dict[int, ActionRawUnitCommand]:
        return {u: a for a in self.bot.state.actions_unit_commands for u in a.unit_tags}

    @cached_property
    def bases(self) -> frozenset[Point2]:
        if self.bot.is_micro_map:
            return frozenset()
        else:
            return frozenset(self.bot.expansion_locations_list)

    @property
    def map_center(self) -> Point2:
        return self.bot.game_info.map_center

    @property
    def start_location(self) -> Point2:
        return self.bot.start_location

    @property
    def bases_taken(self) -> set[Point2]:
        return {b for b in self.bot.expansion_locations_list if (th := self.bot.townhall_at.get(b)) and th.is_ready}

    @cached_property
    def distance_matrix(self) -> dict[tuple[Unit, Unit], float]:
        a = self.units
        b = self.enemy_units
        if not a:
            return {}
        if not b:
            return {}
        distances = pairwise_distances(
            [ai.position for ai in a],
            [bj.position for bj in b],
        )
        distance_matrix = {(ai, bj): distances[i, j] for (i, ai), (j, bj) in product(enumerate(a), enumerate(b))}
        return distance_matrix
