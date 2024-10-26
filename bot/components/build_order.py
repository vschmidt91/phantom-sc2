from sc2.ids.unit_typeid import UnitTypeId

from .component import Component


class BuildOrder(Component):

    def run_build_order(self) -> bool:
        steps = [
            (UnitTypeId.DRONE, 13),
            (UnitTypeId.OVERLORD, 2),
            (UnitTypeId.DRONE, 16),
            (UnitTypeId.HATCHERY, 2),
            (UnitTypeId.EXTRACTOR, 1),
            (UnitTypeId.DRONE, 17),
            (UnitTypeId.SPAWNINGPOOL, 1),
        ]
        for i, (item, count) in enumerate(steps):
            if self.count(item, include_planned=False) < count:
                if self.count(item, include_planned=True) < count:
                    plan = self.add_plan(item)
                    plan.priority = -i
                return False
        return True
