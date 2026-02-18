from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

if TYPE_CHECKING:
    from phantom.main import PhantomBot
    from phantom.micro.combat import CombatSituation


@dataclass(frozen=True)
class Observation:
    bot: PhantomBot
    enemy_combatants: Units
    combatants: Units
    queens: Units
    overseers: Units
    harvester_return_targets: Units
    combat: CombatSituation | None = None
    scout_overlord_tag: int | None = None
    scout_proxy_overlord_tags: tuple[int, ...] = ()
    should_inject: bool = False
    should_spread_creep: bool = False
    detection_targets: tuple[Point2, ...] = ()
    active_tumors: tuple[Unit, ...] = ()


def build_observation(bot: PhantomBot) -> Observation:
    from sc2.ids.unit_typeid import UnitTypeId

    from phantom.common.constants import CIVILIANS, ENEMY_CIVILIANS

    enemy_combatants = bot.enemy_units.exclude_type(ENEMY_CIVILIANS)
    combatants = bot.units.exclude_type({*CIVILIANS, UnitTypeId.QUEEN, UnitTypeId.QUEENBURROWED})
    queens = bot.units({UnitTypeId.QUEEN, UnitTypeId.QUEENBURROWED})
    overseers = bot.units({UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE})
    return Observation(
        bot=bot,
        enemy_combatants=enemy_combatants,
        combatants=combatants,
        queens=queens,
        overseers=overseers,
        harvester_return_targets=bot.townhalls.ready,
    )


def with_micro(observation: Observation, **kwargs) -> Observation:
    return replace(observation, **kwargs)
