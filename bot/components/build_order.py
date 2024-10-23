from functools import cached_property

from ares.consts import ALL_STRUCTURES, UnitRole
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ..action import Action, Build, DoNothing, Research, Train, UseAbility
from .component import Component


class BuildOrder(Component):

    def run_build_order(self) -> bool:
        steps = [
            (UnitTypeId.DRONE, 13),
            (UnitTypeId.OVERLORD, 2),
            (UnitTypeId.DRONE, 16),
            (UnitTypeId.HATCHERY, 2),
            (UnitTypeId.DRONE, 18),
            (UnitTypeId.EXTRACTOR, 1),
            (UnitTypeId.SPAWNINGPOOL, 1),
        ]
        for i, (item, count) in enumerate(steps):
            if self.count(item, include_planned=False) < count:
                if (
                    self.count(item, include_planned=True) < count
                ):
                    plan = self.add_plan(item)
                    plan.priority = -i
                return False
        return True
