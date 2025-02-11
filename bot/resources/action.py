import math
from dataclasses import dataclass
from functools import cached_property

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units

from bot.common.action import Action, DoNothing, Smart
from bot.resources.gather import GatherAction, ReturnResource
from bot.resources.observation import HarvesterAssignment, ResourceObservation


@dataclass(frozen=True)
class ResourceAction:
    observation: ResourceObservation
    old_assignment: HarvesterAssignment
    roach_rushing = True  # TODO

    @cached_property
    def next_assignment(self) -> HarvesterAssignment:
        if not self.observation.mineral_fields:
            return HarvesterAssignment({})

        assignment = self.old_assignment
        assignment = self.observation.update_assignment(assignment)
        assignment = self.observation.update_balance(assignment, self.gas_target)

        return assignment

    @cached_property
    def gas_target(self) -> int:
        if self.roach_rushing and self.observation.bot.count(UnitTypeId.ROACH, include_planned=False) < 8:
            return 3 * self.observation.gas_buildings.ready.amount
        return math.ceil(len(self.old_assignment) * self.observation.gas_ratio)

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.next_assignment.get(unit.tag)):
            logger.error(f"Unassinged harvester {unit}")
            return None
        if not (target := self.observation.resource_at.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        if target.is_vespene_geyser:
            if not (target := self.observation.gas_building_at.get(target_pos)):
                logger.error(f"No gas building found at {target_pos}")
                return None
        if unit.is_idle:
            return Smart(unit, target)
        elif 2 <= len(unit.orders):
            return DoNothing()
        elif unit.is_gathering:
            return GatherAction(unit, target, self.observation.bot.speedmining_positions.get(target_pos))
        elif unit.is_returning:
            assert any(return_targets)
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return ReturnResource(unit, return_target)
        return Smart(unit, target)
