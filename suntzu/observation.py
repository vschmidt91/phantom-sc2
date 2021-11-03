

from collections import defaultdict
from typing import DefaultDict, Dict, Iterable, Optional, Set, Union, List

from s2clientprotocol.sc2api_pb2 import Macro
from sc2.constants import ALL_GAS
from sc2.data import Alliance
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from sc2.unit import Unit
from .macro_plan import MacroPlan

from .constants import  UNIT_BY_TRAIN_ABILITY, UPGRADE_BY_RESEARCH_ABILITY, WORKERS, TRAINERS

class Observation(object):

    def __init__(self):

        self.resource_by_position: Dict[Point2, Unit] = dict()
        self.unit_by_tag: Dict[int, Unit] = dict()
        self.actual_by_type: DefaultDict[Union[UnitTypeId, UpgradeId], Set[int]] = defaultdict(lambda:set())
        self.pending_by_type: DefaultDict[Union[UnitTypeId, UpgradeId], Set[Unit]] = defaultdict(lambda:set())
        self.planned_by_type: DefaultDict[Union[UnitTypeId, UpgradeId], Set[MacroPlan]] = defaultdict(lambda:set())
        self.worker_supply_fixed: int = None
        self.destructables: Set[Unit] = set()

    def clear(self):
        self.resource_by_position.clear()
        self.unit_by_tag.clear()
        self.pending_by_type.clear()
        self.destructables.clear()
        self.worker_supply_fixed = None

    def add_destructable(self, unit: Unit):
        if 0 < unit.armor:
            self.destructables.add(unit)

    def add_resource(self, unit: Unit):
        if unit.type_id in ALL_GAS:
            raise Exception
        self.resource_by_position[unit.position] = unit

    def add_unit(self, unit: Unit):
        self.unit_by_tag[unit.tag] = unit
        if not unit.is_ready:
            self.pending_by_type[unit.type_id].add(unit)
        # if unit.type_id in TRAINERS:
        for order in unit.orders:
            ability = order.ability.exact_id
            training = UNIT_BY_TRAIN_ABILITY.get(ability) or UPGRADE_BY_RESEARCH_ABILITY.get(ability)
            if training:
                self.pending_by_type[training].add(unit)

    def remove_unit(self, unit: Unit):
        pass

    def add_pending(self, item: Union[UnitTypeId, UpgradeId], unit: Unit):
        self.pending_by_type[item].add(unit)

    def add_upgrade(self, upgrade: UpgradeId):
        self.actual_by_type[upgrade].add(None)

    def add_plan(self, plan: MacroPlan):
        self.planned_by_type[plan.item].add(plan)

    def remove_plan(self, plan: MacroPlan):
        self.planned_by_type[plan.item].remove(plan)

    def count(self,
        item: Union[UnitTypeId, UpgradeId],
        include_pending: bool = True,
        include_planned: bool = True,
        include_actual: bool = True
    ) -> int:
        
        sum = 0
        if include_actual:
            if item in WORKERS and self.worker_supply_fixed is not None:
                sum += self.worker_supply_fixed
                # fix worker count (so that it includes workers in gas buildings)
                # sum += self.supply_used - self.supply_army - len(self.pending_by_type[item])
            else:
                sum += len(self.actual_by_type[item])
        if include_pending:
            sum += len(self.pending_by_type[item])
        if include_planned:
            sum += len(self.planned_by_type[item])

        return sum