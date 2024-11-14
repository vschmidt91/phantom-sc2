from dataclasses import dataclass

from loguru import logger
from sc2.unit import Unit
from sc2.units import Units

from bot.common.action import Action, DoNothing, Smart
from bot.components.resources.context import HarvesterAssignment
from bot.components.resources.gather import GatherAction, ReturnResource
from bot.components.resources.main import ResourceContext


@dataclass(frozen=True)
class ResourceReport:
    context: ResourceContext
    assignment: HarvesterAssignment
    gas_target: int

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.assignment.get(unit.tag)):
            logger.error(f"Unassinged harvester {unit}")
            return None
        if not (target := self.context.resource_at.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        if target.is_vespene_geyser:
            if not (target := self.context.gas_building_at.get(target_pos)):
                logger.error(f"No gas building found at {target_pos}")
                return None
        if unit.is_idle:
            return Smart(unit, target)
        elif 2 <= len(unit.orders):
            return DoNothing()
        elif unit.is_gathering:
            return GatherAction(unit, target, self.context.bot.speedmining_positions.get(target_pos))
        elif unit.is_returning:
            assert any(return_targets)
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return ReturnResource(unit, return_target)
        return Smart(unit, target)
