from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from itertools import chain
import itertools
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Type,
    TypeVar,
)

import numpy as np
import skimage.draw
from sc2.data import race_townhalls
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit, UnitCommand
from scipy.spatial import cKDTree

from src.units.unit import UnitChangedEvent

from ..constants import ITEM_BY_ABILITY
from ..units.army import Army
from ..units.creep_tumor import CreepTumor
from ..units.extractor import Extractor
from ..units.changeling import Changeling
from ..units.overlord import Overlord
from ..units.queen import Queen
from ..units.structure import Hatchery, Larva, Structure
from ..units.unit import AIUnit, Behavior
from ..units.worker import Worker
from .macro import MacroId
from .module import AIModule

if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
}

# VISIBILITY_OFFSETS = np.array([
#     [0, 0],
#     [-1, 0],
#     [+1, 0],
#     [0, -1],
#     [0, +1],
# ])
T = TypeVar("T")


@dataclass
class PendingEntry:
    item: MacroId
    trainer: AIUnit


BehaviorTable = Dict[UnitTypeId, Any]

DEFAULT_BEHAVIORS: BehaviorTable = {
    UnitTypeId.EXTRACTOR: Extractor,
    UnitTypeId.EXTRACTORRICH: Extractor,
    UnitTypeId.CREEPTUMOR: CreepTumor,
    UnitTypeId.CREEPTUMORBURROWED: CreepTumor,
    UnitTypeId.CREEPTUMORQUEEN: CreepTumor,
    UnitTypeId.LARVA: Larva,
    UnitTypeId.HATCHERY: Hatchery,
    UnitTypeId.LAIR: Hatchery,
    UnitTypeId.HIVE: Hatchery,
    UnitTypeId.OVERLORD: Overlord,
    UnitTypeId.QUEEN: Queen,
    UnitTypeId.OVERSEER: Overlord,
    UnitTypeId.ZERGLING: Army,
    UnitTypeId.ZERGLINGBURROWED: Army,
    UnitTypeId.ROACH: Army,
    UnitTypeId.ROACHBURROWED: Army,
    UnitTypeId.HYDRALISK: Army,
    UnitTypeId.HYDRALISKBURROWED: Army,
    UnitTypeId.ULTRALISK: Army,
    UnitTypeId.ULTRALISKBURROWED: Army,
    UnitTypeId.MUTALISK: Army,
    UnitTypeId.CORRUPTOR: Army,
    UnitTypeId.BROODLORD: Army,
    UnitTypeId.DRONE: Worker,
    UnitTypeId.DRONEBURROWED: Worker,
    UnitTypeId.SCV: Worker,
    UnitTypeId.MULE: Worker,
    UnitTypeId.PROBE: Worker,
    UnitTypeId.SPAWNINGPOOL: Structure,
    UnitTypeId.ROACHWARREN: Structure,
    UnitTypeId.HYDRALISKDEN: Structure,
    UnitTypeId.LURKERDEN: Structure,
    UnitTypeId.ULTRALISKCAVERN: Structure,
    UnitTypeId.EVOLUTIONCHAMBER: Structure,
    UnitTypeId.INFESTATIONPIT: Structure,
    UnitTypeId.SPIRE: Structure,
    UnitTypeId.GREATERSPIRE: Structure,
    UnitTypeId.SPINECRAWLER: Structure,
    UnitTypeId.SPINECRAWLERUPROOTED: Structure,
    UnitTypeId.SPORECRAWLER: Structure,
    UnitTypeId.SPORECRAWLERUPROOTED: Structure,
    UnitTypeId.CHANGELING: Changeling,
}


class UnitManager(AIModule):
    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.behavior_table: BehaviorTable = DEFAULT_BEHAVIORS
        self.unit_by_tag: Dict[int, Unit] = dict()

        self.units: Dict[int, AIUnit] = dict()
        self.enemies: Dict[int, Unit] = dict()

    @property
    def townhalls(self) -> Iterable[Structure]:
        return (
            townhall
            for townhall in self.behavior_of_type(Structure)
            if townhall.unit.state.type_id in race_townhalls[self.ai.race]
        )

    def actual_by_type(self, type_id: MacroId) -> List[AIUnit]:
        if isinstance(type_id, UnitTypeId):
            return [
                unit
                for unit in self.units.values()
                if (unit.state.type_id == type_id and unit.state.is_ready)
            ]
        elif isinstance(type_id, UpgradeId):
            if type_id in self.ai.state.upgrades:
                return [None]
            else:
                return []
        else:
            return []

    def pending_by_type(self, type_id: MacroId) -> List[AIUnit]:
        return list(
            itertools.chain(
                (
                    unit
                    for unit in self.units.values()
                    if (unit.state.type_id == type_id and not unit.state.is_ready)
                ),
                (
                    unit
                    for unit in self.units.values()
                    for order in unit.state.orders
                    if ITEM_BY_ABILITY.get(order.ability.exact_id) == type_id
                ),
            )
        )

    def add_unit(self, state: Unit) -> Optional[AIUnit]:
        if state.type_id in IGNORED_UNIT_TYPES:
            return None
        elif state.is_mine:
            unit = AIUnit(self.ai, state)
            if (behavior := self.create_behavior(unit)):
                unit.behavior = behavior
                unit.on_destroyed.subscribe(self.remove_unit)
                self.units[state.tag] = unit
            return unit
        elif state.is_enemy:
            return None
        else:
            return None

    def remove_unit(self, event: UnitChangedEvent) -> None:
        self.units.pop(event.unit.state.tag, None)

    def try_remove_unit(self, tag: int) -> bool:
        if self.units.pop(tag, None) is not None:
            return True
        elif self.enemies.pop(tag, None) is not None:
            return True
        else:
            return False

    def create_behavior(self, unit: AIUnit) -> Optional[Behavior]:
        behavior_cls = self.behavior_table.get(unit.state.type_id)
        if not behavior_cls:
            return None
        behavior = behavior_cls(unit)
        return behavior

    def of_type(self, type: Type[T]) -> Iterable[T]:
        return (unit for unit in self.units.values() if isinstance(unit, type))

    def behavior_of_type(self, type: Type[T]) -> Iterable[T]:
        return (
            unit.behavior
            for unit in self.units.values()
            if isinstance(unit.behavior, type)
        )

    def update_tags(self) -> None:
        self.unit_by_tag = {unit.tag: unit for unit in self.ai.all_own_units}
        for tag, unit in list(self.units.items()):
            new_state = self.unit_by_tag.get(tag)
            unit.update_state(new_state)

        visibility_map = self.ai.state.visibility.data_numpy.transpose()
        for tag, enemy in self.enemies.copy().items():
            if enemy.game_loop + 3000 < self.ai.state.game_loop:
                del self.enemies[tag]
                continue
            visibility_disk = skimage.draw.disk(
                center=enemy.position, radius=1, shape=self.ai.game_info.map_size
            )
            visibility = visibility_map[visibility_disk] == 2
            if np.all(visibility):
                del self.enemies[tag]
                continue
        self.enemies.update(
            (unit.tag, unit) for unit in self.ai.all_enemy_units if not unit.is_snapshot
        )

    async def on_step(self) -> None:
        self.update_tags()

        commands: List[UnitCommand] = []
        commands_skipped: List[UnitCommand] = []
        for unit in list(self.units.values()):
            # unit.on_step()
            if not unit.behavior:
                continue
            command = unit.behavior.get_command()
            if not command:
                continue
            if any(
                self.ai.order_matches_command(o, command) for o in command.unit.orders
            ):
                commands_skipped.append(command)
                continue
            # if (
            #     command.ability == AbilityId.MOVE
            #     and command.target.distance_to(unit.state.position) < 0.5
            # ):
            #     continue
            commands.append(command)
            result = self.ai.do(command, subtract_cost=False, subtract_supply=False)

            if not result:
                logging.error(f"command failed: {command}")

        logging.debug(f"Commands: {Counter(c.ability for c in commands)}")
        # logging.debug(f"Commands skipped: {Counter(c.ability for c in commands_skipped)}")
        # logging.debug(f"{len(commands)} commands, {len(commands_skipped)} skipped")

        optimal_game_step = max(self.ai.min_game_step, len(commands) // 40)
        if self.ai.client.game_step != optimal_game_step:
            logging.info(f"changin game_step to {optimal_game_step}")
            self.ai.client.game_step = optimal_game_step

        self.unit_by_position = {
            unit.position: unit
            for unit in chain(self.ai.all_own_units, self.ai.all_enemy_units)
        }
        self.unit_positions = list(self.unit_by_position.keys())
        self.unit_tree = cKDTree(np.array(self.unit_positions))

    def units_in_circle(self, position: Point2, radius: float) -> Iterable[Unit]:
        result = self.unit_tree.query_ball_point(position, radius)
        return (self.unit_by_position[self.unit_positions[i]] for i in result)
