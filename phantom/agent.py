import math
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

import numpy as np
from ares.consts import UnitRole
from cython_extensions import cy_closest_to
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.combat import CombatState
from phantom.common.action import Action, Attack, Move, UseAbility
from phantom.common.constants import CHANGELINGS, ENERGY_COST, GAS_BY_RACE
from phantom.common.cost import Cost
from phantom.common.distribute import distribute
from phantom.common.utils import pairwise_distances
from phantom.corrosive_bile import CorrosiveBile
from phantom.creep import CreepState
from phantom.dodge import DodgeState
from phantom.macro.build_order import BUILD_ORDERS
from phantom.macro.main import MacroPlan, MacroState
from phantom.macro.strategy import StrategyState
from phantom.observation import ObservationState
from phantom.parameters import Parameters
from phantom.resources.main import ResourceState
from phantom.resources.observation import ResourceObservation
from phantom.scout import ScoutState
from phantom.transfuse import TransfuseAction

if TYPE_CHECKING:
    from phantom.main import PhantomBot


@dataclass
class Agent:
    def __init__(self, bot: "PhantomBot", build_order_name: str, parameters: Parameters) -> None:
        self.bot = bot
        self.build_order = BUILD_ORDERS[build_order_name]
        self.parameters = parameters
        self.combat = CombatState(bot, parameters)
        self.observation = ObservationState(bot)
        self.macro = MacroState(bot)
        self.creep = CreepState(bot)
        self.corrosive_biles = CorrosiveBile()
        self.dodge = DodgeState()
        self.scout = ScoutState(bot)
        self.strategy = StrategyState(bot, parameters)
        self.resources = ResourceState(bot)
        self.build_order_completed = False

    async def step(self) -> Mapping[Unit, Action]:
        planned = Counter(p.item for p in self.macro.enumerate_plans())
        observation = self.observation.step(planned)

        strategy = self.strategy.step(observation)

        build_order_actions = dict[Unit, Action]()
        if not self.bot.is_micro_map:
            if not self.build_order_completed:
                if step := self.build_order.execute(observation):
                    build_order_actions.update(step.actions)
                    for plan in step.plans:
                        self.macro.add(plan)
                else:
                    logger.info("Build order completed.")
                    self.build_order_completed = True
            else:
                for plan in chain(
                    self.macro.make_composition(observation, strategy.composition_target),
                    strategy.make_upgrades(),
                    strategy.morph_overlord(),
                    strategy.expand(),
                    strategy.make_spores(),
                ):
                    self.macro.add(plan)

        combat = self.combat.step(observation)
        transfuse = TransfuseAction(observation)
        creep = self.creep.step()

        injecters = observation.units(UnitTypeId.QUEEN)
        inject_targets = observation.townhalls.ready
        inject_assignment = distribute(
            injecters,
            inject_targets,
            pairwise_distances(
                [a.position for a in injecters],
                [b.position for b in inject_targets],
            ),
        )
        dodge = self.dodge.step(observation)
        dode_actions = {u: a for u in observation.units if (a := dodge.dodge_with(u))}

        macro_step = self.macro.step(observation, set(self.scout.blocked_positions))
        macro_actions = macro_step.get_actions()

        should_inject = observation.supply_used + observation.bank.larva < 200
        should_spread_creep = self.creep.unspread_tumor_count < 50

        def should_harvest_resource(r: Unit) -> bool:
            p = tuple(r.position.rounded)
            check_points = [
                self.bot.speedmining_positions[p].rounded,
                tuple(self.bot.return_point[p].rounded),
            ]
            return all(self.bot.mediator.get_ground_grid[p] < 6.0 for p in check_points)

        harvesters = self.bot.mediator.get_units_from_role(role=UnitRole.GATHERING)

        if self.bot.is_micro_map:
            resources_to_harvest = observation.resources
            gas_ratio = 0.0
        else:
            resources_to_harvest = observation.all_taken_resources.filter(should_harvest_resource)
            required = Cost()
            required += sum((self.bot.cost.of(plan.item) for plan in self.macro.unassigned_plans), Cost())
            required += sum(
                (self.bot.cost.of(plan.item) for plan in self.macro.assigned_plans.values()),
                Cost(),
            )
            required += self.bot.cost.of_composition(strategy.composition_deficit)
            required -= observation.bank

            if required.minerals <= 0 and required.vespene <= 0:
                # TODO
                optimal_gas_ratio = 5 / 9
            else:
                mineral_trips = max(0.0, required.minerals / 5)
                vespene_trips = max(0.0, required.vespene / 4)
                optimal_gas_ratio = vespene_trips / (mineral_trips + vespene_trips)
            gas_ratio = optimal_gas_ratio

        resources = self.resources.step(
            ResourceObservation(
                observation,
                harvesters,
                observation.gas_buildings.ready,
                resources_to_harvest.vespene_geyser,
                resources_to_harvest.mineral_field,
                gas_ratio,
            )
        )
        harvester_return_targets = observation.townhalls.ready

        gas_type = GAS_BY_RACE[self.bot.race]
        gas_depleted = observation.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_have = (
            observation.count_actual(gas_type)
            + observation.count_pending(gas_type)
            + observation.count_planned(gas_type)
        )
        gas_max = resources.observation.vespene_geysers.amount
        gas_want = min(gas_max, gas_depleted + math.ceil((resources.gas_target - 1) / 3))
        # if not observation.count(UnitTypeId.LAIR, include_planned=False):
        #     gas_want = min(1, gas_want)
        if gas_have < gas_want:
            self.macro.add(MacroPlan(gas_type))

        def inject_with_queen(q: Unit) -> Action | None:
            if not should_inject:
                return None
            if q.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
                return None
            if target := inject_assignment.get(q):
                if target.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    return None
                return UseAbility(AbilityId.EFFECT_INJECTLARVA, target=target)
            return None

        def micro_queen(q: Unit) -> Action | None:
            p = tuple(q.position.rounded)
            return (
                transfuse.transfuse_with(q)
                or (combat.fight_with(q) if 1 < self.bot.mediator.get_ground_grid[p] < np.inf else None)
                or inject_with_queen(q)
                or (creep.spread_with_queen(q) if should_spread_creep else None)
                or (combat.retreat_with(q) if not observation.creep[p] else None)
                or combat.fight_with(q)
            )

        def micro_overseers(overseers: Units) -> Mapping[Unit, Action]:
            targets = distribute(
                overseers,
                observation.enemy_combatants,
                pairwise_distances(
                    [a.position for a in overseers],
                    [b.position for b in observation.enemy_combatants],
                ),
            )

            def micro_overseer(u: Unit) -> Action | None:
                local_threat = self.bot.mediator.get_air_grid[u.position.rounded] - 1
                if action := ((combat.retreat_with(u) if local_threat > 0 else None) or spawn_changeling(u)):
                    return action
                elif target := targets.get(u):
                    target_point = observation.find_path(
                        start=u.position,
                        target=target.position,
                        air=True,
                    )
                    return Move(target_point)
                return None

            return {u: a for u in overseers if (a := micro_overseer(u))}

        def micro_harvester(u: Unit) -> Action | None:
            return (
                (
                    combat.retreat_with(u)
                    if 6.0 < self.bot.mediator.get_ground_grid[u.position.rounded] < np.inf
                    else None
                )
                or resources.gather_with(u, harvester_return_targets)
                # or (drone_scout(u) if harvester_return_targets.amount < 2 else None)
            )

        def micro_overlord(u: Unit) -> Action | None:
            if not self.bot.mediator.is_position_safe(grid=self.bot.mediator.get_air_grid, position=u.position):
                return combat.retreat_with(u)
            return None

        micro_handlers = {
            UnitTypeId.BANELING: combat.fight_with_baneling,
            UnitTypeId.ROACH: combat.do_burrow,
            UnitTypeId.ROACHBURROWED: combat.do_unburrow,
            UnitTypeId.QUEEN: micro_queen,
        }

        def micro_unit(u: Unit) -> Action | None:
            if (handler := micro_handlers.get(u.type_id)) and (action := handler(u)):
                return action
            return combat.fight_with(u) or search_with(u)

        def spawn_changeling(unit: Unit) -> Action | None:
            if (
                not observation.pathing[unit.position.rounded]
                or unit.energy < ENERGY_COST[AbilityId.SPAWNCHANGELING_SPAWNCHANGELING]
            ):
                return None
            return UseAbility(AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)

        def search_with(unit: Unit) -> Action | None:
            if not (unit.is_idle or unit.is_gathering or unit.is_returning):
                return None
            elif observation.time < 8 * 60 and self.bot.enemy_start_locations:
                return Move(Point2(random.choice(self.bot.enemy_start_locations)))
            elif observation.enemy_combatants:
                target = cy_closest_to(unit.position, observation.enemy_combatants)
                return Attack(target.position)
            elif observation.enemy_units:
                target = cy_closest_to(unit.position, observation.enemy_units)
                return Attack(target.position)
            target = observation.random_point(near=unit.position)
            if observation.is_visible[target.rounded]:
                return None
            if not observation.pathing[target.rounded] and not unit.is_flying:
                return None
            return Move(target)

        detectors = observation.units(UnitTypeId.OVERSEER)
        scout_actions = self.scout.step(observation, detectors)

        actions = {
            **build_order_actions,
            **{u: a for u in harvesters if (a := micro_harvester(u))},
            **creep.spread_active_tumors(),
            **micro_overseers(observation.overseers),
            **scout_actions,
            **{u: a for u in observation.units(UnitTypeId.OVERLORD) if (a := micro_overlord(u))},
            **{u: a for u in observation.units(CHANGELINGS) if (a := search_with(u))},
            **{u: a for u in observation.combatants if (a := micro_unit(u))},
            **{
                u: UseAbility(AbilityId.CANCEL)
                for u in observation.structures
                if not u.is_ready and u.health_percentage < 0.1
            },
            **macro_actions,
            **self.corrosive_biles.step(observation),
            **dode_actions,
        }

        return actions

    def on_building_construction_started(self, unit: Unit) -> None:
        pass

    def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId) -> None:
        if unit.type_id == UnitTypeId.CREEPTUMORBURROWED:
            self.creep.on_tumor_completed(unit, previous_type == UnitTypeId.CREEPTUMORQUEEN)
