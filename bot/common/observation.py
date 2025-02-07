from dataclasses import dataclass
from functools import cached_property

import numpy as np
from sc2.game_state import ActionRawUnitCommand
from sc2.position import Point2
from sc2.units import Units

from bot.common.main import BotBase


@dataclass(frozen=True)
class Observation:
    bot: BotBase

    @property
    def units(self) -> Units:
        return self.bot.units

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
        return self.bot.mediator.get_map_data_object.get_pyastar_grid() == 1.0

    @cached_property
    def unit_commands(self) -> dict[int, ActionRawUnitCommand]:
        return {u: a for a in self.bot.state.actions_unit_commands for u in a.unit_tags}

    @cached_property
    def bases(self) -> frozenset[Point2]:
        if self.bot.is_micro_map:
            return frozenset()
        else:
            return frozenset(self.bot.expansion_locations_list)
