from typing import TYPE_CHECKING

from ares import UnitTreeQueryType
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from phantom.common.action import Action, UseAbility

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class Transfuse:
    def __init__(self, bot: "PhantomBot"):
        self.bot = bot
        self.ability = AbilityId.TRANSFUSION_TRANSFUSION
        self.ability_range = bot.game_data.abilities[self.ability.value]._proto.cast_range
        self.ability_energy_cost = 50
        self.min_wounded = 75
        self.transfuse_structures = {UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER}

    def transfuse_with(self, unit: Unit) -> Action | None:
        if unit.energy < self.ability_energy_cost:
            return None

        (targets,) = self.bot.mediator.get_units_in_range(
            start_points=[unit],
            distances=[unit.radius + self.ability_range],
            query_tree=UnitTreeQueryType.AllOwn,
        )

        def is_eligible(t: Unit) -> bool:
            return (
                t != unit
                and BuffId.TRANSFUSION not in t.buffs
                and t.health + self.min_wounded <= t.health_max
                and (not t.is_structure or t.type_id in self.transfuse_structures)
            )

        def priority(t: Unit) -> float:
            return 1 - t.shield_health_percentage

        if target := max(filter(is_eligible, targets), key=priority, default=None):
            return UseAbility(self.ability, target=target)

        return None
