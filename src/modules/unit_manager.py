from __future__ import annotations

from typing import DefaultDict, List, TYPE_CHECKING, Optional, Dict, Iterable
from collections import defaultdict

from sc2.data import race_townhalls
from sc2.unit import Unit, UnitTypeId

from ..units.army import Army
from ..units.changeling import Changeling
from ..units.creep_tumor import CreepTumor
from ..units.overlord import Overlord
from ..units.queen import Queen
from ..units.unit import AIUnit, CommandableUnit, EnemyUnit, IdleBehavior
from ..units.worker import Worker
from .macro import MacroId
from .module import AIModule
from ..constants import WORKERS, CHANGELINGS, ITEM_BY_ABILITY
from ..units.extractor import Extractor
from ..units.structure import Larva, Structure

if TYPE_CHECKING:
    from ..ai_base import AIBase

IGNORED_UNIT_TYPES = {
    UnitTypeId.BROODLING,
    UnitTypeId.LOCUSTMP,
    UnitTypeId.LOCUSTMPFLYING,
}


class UnitManager(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)

        self.units: Dict[int, CommandableUnit] = dict()
        self.enemies: Dict[int, EnemyUnit] = dict()
        # self.neutrals: Dict[int, AIUnit] = dict()

        self.actual_by_type: DefaultDict[MacroId, List[CommandableUnit]] = defaultdict(list)
        self.pending_by_type: DefaultDict[MacroId, List[CommandableUnit]] = defaultdict(list)

    @property
    def townhalls(self) -> Iterable[Structure]:
        return (
            townhall
            for townhall_type in race_townhalls[self.ai.race]
            for townhall in self.actual_by_type[townhall_type]
            if isinstance(townhall, Structure)
        )

    def update_tables(self):

        self.actual_by_type.clear()
        self.pending_by_type.clear()

        for behavior in self.units.values():
            self.add_unit_to_tables(behavior)

        for upgrade in self.ai.state.upgrades:
            self.actual_by_type[upgrade] = [None]

    def add_unit_to_tables(self, behavior: CommandableUnit) -> None:
        if not behavior.unit:
            pass
        elif behavior.unit.is_ready:
            self.actual_by_type[behavior.unit.type_id].append(behavior)
            for order in behavior.unit.orders:
                if item := ITEM_BY_ABILITY.get(order.ability.exact_id):
                    self.pending_by_type[item].append(behavior)
        else:
            self.pending_by_type[behavior.unit.type_id].append(behavior)

    def add_unit(self, unit: Unit) -> Optional[AIUnit]:
        if unit.type_id in IGNORED_UNIT_TYPES:
            return None
        elif unit.is_mine:
            behavior = self.create_unit(unit)
            self.add_unit_to_tables(behavior)
            self.units[unit.tag] = behavior
            return behavior
        elif unit.is_enemy:
            enemy = EnemyUnit(self.ai, unit)
            self.enemies[unit.tag] = enemy
            return enemy
        else:
            return None
        # elif unit.is_mineral_field or unit.is_vespene_geyser:
        #     behavior = ResourceUnit(self.ai, unit.position)
        #     self.resources[unit.position] = behavior
        # else:
        #     behavior = AIUnit(self.ai, unit)
        #     self.neutrals[unit.tag] = behavior

    def try_remove_unit(self, tag: int) -> bool:
        return any((
            self.units.pop(tag, None),
            self.enemies.pop(tag, None),
            # self.neutrals.pop(tag, None),
        ))

    def create_unit(self, unit: Unit) -> CommandableUnit:

        if unit.type_id in IGNORED_UNIT_TYPES:
            return IdleBehavior(self.ai, unit)
        if unit.type_id in CHANGELINGS:
            return Changeling(self.ai, unit)
        elif unit.type_id in { UnitTypeId.EXTRACTOR, UnitTypeId.EXTRACTORRICH }:
            return Extractor(self.ai, unit)
        elif unit.type_id in {
            UnitTypeId.CREEPTUMOR,
            UnitTypeId.CREEPTUMORBURROWED,
            UnitTypeId.CREEPTUMORQUEEN
        }:
            return CreepTumor(self.ai, unit)
        elif unit.type_id == UnitTypeId.LARVA:
            return Larva(self.ai, unit)
        elif unit.type_id in WORKERS:
            return Worker(self.ai, unit)
        elif unit.type_id == UnitTypeId.OVERLORD:
            return Overlord(self.ai, unit)
        elif unit.type_id == UnitTypeId.QUEEN:
            return Queen(self.ai, unit)
        elif self.ai.techtree.units[unit.type_id].is_structure:
            return Structure(self.ai, unit)
        else:
            return Army(self.ai, unit)

    def update_tags(self) -> None:

        unit_by_tag = {
            unit.tag: unit
            for unit in self.ai.all_own_units
        }
        for tag, unit in self.units.items():
            unit.unit = unit_by_tag.get(tag)

        # neutral_by_tag = {
        #     unit.tag: unit
        #     for unit in self.ai.all_units
        #     if unit.alliance == Alliance.Neutral
        # }
        # for tag, unit in self.neutrals.items():
        #     unit.unit = neutral_by_tag.get(tag)

        enemy_by_tag = {
            unit.tag: unit
            for unit in self.ai.all_enemy_units
        }
        for tag, enemy in list(self.enemies.items()):
            if new_unit := enemy_by_tag.get(tag):
                enemy.unit = new_unit
            elif self.ai.is_visible(enemy.unit.position):
                del self.enemies[tag]

    async def on_step(self) -> None:
        self.update_tags()
        self.update_tables()
        for unit in self.units.values():
            unit.on_step()
        for enemy in self.enemies.values():
            enemy.on_step()