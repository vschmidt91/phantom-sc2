from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from cython_extensions import cy_distance_to
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sklearn.metrics import pairwise_distances

from phantom.common.action import Action, HoldPosition, Move, UseAbility
from phantom.common.constants import ENERGY_GENERATION_RATE
from phantom.common.distribute import distribute
from phantom.micro.creep import CreepSpread
from phantom.micro.main import CombatStep
from phantom.micro.transfuse import Transfuse

if TYPE_CHECKING:
    from phantom.main import PhantomBot


class Queens:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.transfuse = Transfuse(bot)

    def get_actions(
        self, queens: Sequence[Unit], inject_targets: Sequence[Unit], creep: CreepSpread | None, combat: CombatStep
    ) -> Mapping[Unit, Action]:
        inject_assignment = (
            distribute(
                inject_targets,
                queens,
                pairwise_distances(
                    [b.position for b in inject_targets],
                    [a.position for a in queens],
                ),
                max_assigned=1,
            )
            if queens and inject_targets
            else {}
        )
        inject_assignment_inverse = {q: h for h, q in inject_assignment.items()}
        actions = {
            queen: action
            for queen in queens
            if (
                action := self._get_action(
                    queen=queen,
                    inject_target=inject_assignment_inverse.get(queen),
                    creep=creep,
                    combat=combat,
                )
            )
        }
        self.transfuse.on_step()
        return actions

    def _get_action(
        self, queen: Unit, inject_target: Unit | None, creep: CreepSpread | None, combat: CombatStep
    ) -> Action | None:
        if action := self.transfuse.transfuse_with(queen):
            return action
        elif not combat.is_unit_safe(queen):
            return combat.fight_with(queen)
        elif inject_target and (action := self._inject_with(queen, inject_target)):  # noqa: SIM114
            return action
        elif creep and (action := creep.spread_with(queen)):
            return action
        elif not self.bot.has_creep(queen):
            return combat.retreat_to_creep(queen)
        elif self.bot.is_on_edge_of_creep(queen):
            return HoldPosition()
        else:
            return combat.fight_with(queen)

    def _inject_with(self, queen: Unit, hatch: Unit) -> Action | None:
        distance = cy_distance_to(queen.position, hatch.position) - queen.radius - hatch.radius
        time_to_reach_target = distance / (1.4 * queen.real_speed)
        time_until_buff_runs_out = hatch.buff_duration_remain / 22.4
        time_to_generate_energy = max(0.0, 25 - queen.energy) / (22.4 * ENERGY_GENERATION_RATE)
        time_until_order = max(time_until_buff_runs_out, time_to_generate_energy)
        if time_until_order == 0:
            return UseAbility(AbilityId.EFFECT_INJECTLARVA, target=hatch)
        elif time_until_order < time_to_reach_target:
            return Move(hatch.position)
        else:
            return None
