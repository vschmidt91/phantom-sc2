from typing import TYPE_CHECKING

from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2

from phantom.common.utils import Point, to_point

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class BlockedPositionTracker:
    def __init__(self, bot: "PhantomBot"):
        self.bot = bot
        self.blocked_positions = dict[Point, float]()

    def on_step(self) -> None:
        for p, blocked_since in list(self.blocked_positions.items()):
            if blocked_since + 60 < self.bot.time:
                logger.info(f"Resetting blocked base {p}")
                del self.blocked_positions[p]

        for error in self.bot.state.action_errors:
            error_ability = AbilityId(error.ability_id)
            error_result = ActionResult(error.result)
            if (
                error_ability not in {AbilityId.BUILD_CREEPTUMOR_TUMOR, AbilityId.BUILD_CREEPTUMOR_QUEEN}
                and error_result in {ActionResult.CantBuildLocationInvalid, ActionResult.CouldntReachTarget}
                and (unit := self.bot._units_previous_map.get(error.unit_tag))
            ):
                p = to_point(unit.order_target) if isinstance(unit.order_target, Point2) else to_point(unit.position)
                if p not in self.blocked_positions:
                    self.blocked_positions[p] = self.bot.time
                    logger.info(f"Detected blocked base {p}")
