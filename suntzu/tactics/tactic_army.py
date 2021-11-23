

from typing import List
from suntzu.behaviors.behavior_base import BehaviorBase
from .tactic_base import TacticBase
from ..common import CommonAI
from ..behaviors.fight import FightBehavior
from ..behaviors.dodge import DodgeBehavior

class TacticArmy(TacticBase):

    def __init__(self, bot: CommonAI):
        super().__init__(bot)
        self.behaviors: List[BehaviorBase] = [
            DodgeBehavior(bot.dodge),
            FightBehavior(bot),
        ]

    def execute(self):
        for tag in self.unit_tags:
            unit = self.bot.unit_by_tag.get(tag)
            if not unit:
                continue
            result = any(b.execute(unit) for b in self.behaviors)