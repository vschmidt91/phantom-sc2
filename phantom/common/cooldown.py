from typing import TYPE_CHECKING

from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class CooldownTracker:
    def __init__(self, bot: "PhantomBot", ability: AbilityId, cooldown: float) -> None:
        self.bot = bot
        self.last_used = dict[int, int]()
        self.ability = ability
        self.cooldown = cooldown

    def on_step(self):
        for action in self.bot.actions_by_ability[self.ability]:
            for tag in action.unit_tags:
                self.last_used[tag] = self.bot.state.game_loop

    def get_cooldown(self, unit: Unit) -> int:
        if last_used := self.last_used.get(unit.tag):
            return max(0, last_used + self.cooldown - self.bot.state.game_loop)
        return 0
