import math
import random
from dataclasses import dataclass
from itertools import chain
from typing import AsyncGenerator, Iterable

import numpy as np
from cython_extensions import cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units

from phantom.knowledge import Knowledge
from phantom.combat.action import CombatAction
from phantom.common.action import Action, Move, UseAbility
from phantom.common.assignment import Assignment
from phantom.common.constants import ALL_MACRO_ABILITIES, CHANGELINGS, ENERGY_COST, GAS_BY_RACE
from phantom.common.distribute import distribute
from phantom.common.utils import pairwise_distances, Point
from phantom.corrosive_biles import CorrosiveBileState
from phantom.creep import CreepState
from phantom.dodge import DodgeState
from phantom.macro.build_order import HATCH_FIRST, HATCH_POOL_HATCH, POOL_FIRST
from phantom.macro.state import MacroPlan, MacroState
from phantom.macro.strategy import Strategy
from phantom.observation import Observation
from phantom.parameters import AgentParameters
from phantom.resources.observation import ResourceObservation
from phantom.resources.state import ResourceState
from phantom.scout import ScoutState
from phantom.transfuse import TransfuseAction


@dataclass(frozen=True)
class Agent:
    parameters: AgentParameters
    knowledge: Knowledge
    macro = MacroState()
    creep = CreepState()
    corrosive_biles = CorrosiveBileState()
    dodge = DodgeState()
    scout = ScoutState()
    resources = ResourceState()
    build_order = HATCH_POOL_HATCH

    async def step(self, observation: Observation) -> AsyncGenerator[Action, None]:
        strategy = Strategy(observation, self.parameters.strategy)

        if not observation.is_micro_map:
            if step := self.build_order.execute(observation):
                for action in step.actions:
                    yield action
                for plan in step.plans:
                    self.macro.add(plan)
            else:
                for plan in chain(
                    self.macro.make_composition(observation, strategy.composition_target),
                    strategy.make_tech(),
                    strategy.morph_overlord(),
                    strategy.expand(),
                ):
                    self.macro.add(plan)

        combat = CombatAction(observation, self.parameters.combat)
        transfuse = TransfuseAction(observation)
        creep = self.creep.step(observation, np.less_equal(0.0, combat.confidence))

        safe_overlord_spots = [p for p in observation.overlord_spots if 0 < combat.confidence[p.rounded]]
        scout = self.scout.step(observation, safe_overlord_spots)

        injecters = observation.units({UnitTypeId.QUEEN})
        injected_targets = observation.townhalls.ready
        inject_assignment = (
            distribute(
                injecters,
                injected_targets,
                pairwise_distances(
                    [a.position for a in injecters],
                    [b.position for b in injected_targets],
                ),
                lp=True,
            )
            if injecters and injected_targets
            else Assignment({})
        )
        dodge = self.dodge.step(observation)
        macro_actions = await self.macro.step(observation, set(self.scout.blocked_positions), combat)

        should_inject = observation.supply_used + observation.bank.larva < 200
        should_spread_creep = self.creep.unspread_tumor_count < 20

        def should_harvest(u: Unit) -> bool:
            if observation.is_micro_map:
                return False
            elif u in macro_actions:  # got special orders?
                return False
            elif u.is_idle:  # you slackin?
                return True
            elif u.orders[0].ability.exact_id in ALL_MACRO_ABILITIES:
                return False  # alright, carry on!
            return True  # get on with it!

        def should_harvest_resource(r: Unit) -> bool:
            check_points = [Point(r.position.rounded)]
            if return_point := self.knowledge.return_point.get(Point(r.position.rounded)):
                check_points.append(return_point)
            for p in check_points:
                if combat.confidence[p] < 0 < combat.enemy_presence.dps[p]:
                    return False
            return True

        harvesters = observation.workers.filter(should_harvest)

        if observation.is_micro_map:
            resources_to_harvest = observation.resources
            gas_ratio = 0.0
        else:
            resources_to_harvest = observation.all_taken_resources.filter(should_harvest_resource)
            required = observation.cost.zero
            required += sum(
                (observation.cost.of(plan.item) for plan in self.macro.unassigned_plans), observation.cost.zero
            )
            required += sum(
                (observation.cost.of(plan.item) for plan in self.macro.assigned_plans.values()),
                observation.cost.zero,
            )
            required += observation.cost.of_composition(strategy.composition_deficit)
            required -= observation.bank

            if required.minerals <= 0 and required.vespene <= 0:
                # TODO
                optimal_gas_ratio = 0.5 if observation.researched_speed else 0.0
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

        gas_type = GAS_BY_RACE[observation.race]
        gas_depleted = observation.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = observation.count(gas_type, include_actual=False)
        gas_have = resources.observation.gas_buildings.amount
        gas_max = resources.observation.vespene_geysers.amount
        gas_want = min(gas_max, gas_depleted + math.ceil((resources.gas_target - 1) / 3))
        if not observation.count(UnitTypeId.LAIR, include_planned=False):
            gas_want = min(1, gas_want)
        if gas_have + gas_pending < gas_want:
            self.macro.add(MacroPlan(gas_type))

        corrosive_biles = self.corrosive_biles.step(observation)

        def inject_with_queen(q: Unit) -> Action | None:
            if not should_inject:
                return None
            if q.energy < ENERGY_COST[AbilityId.EFFECT_INJECTLARVA]:
                return None
            if target := inject_assignment.get(q):
                if target.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    return None
                return UseAbility(q, AbilityId.EFFECT_INJECTLARVA, target=target)
            return None

        def micro_queen(q: Unit) -> Action | None:
            x, y = q.position.rounded
            return (
                transfuse.transfuse_with(q)
                or (combat.fight_with(q) if 0 < combat.enemy_presence.dps[x, y] else None)
                or inject_with_queen(q)
                or (creep.spread_with_queen(q) if should_spread_creep else None)
                or (combat.retreat_with(q, limit=2) if not observation.creep[x, y] else None)
                or combat.fight_with(q)
            )

        def micro_overseers(overseers: Units) -> Iterable[Action]:
            def cost(u: Unit, t: Unit) -> float:
                scout_value = 1.0
                if t.is_structure:
                    scout_value /= 10
                if t.is_burrowed or t.is_cloaked:
                    scout_value *= 10
                distance_others = max((v.distance_to(t) for v in overseers), default=0.0)
                if observation.is_micro_map:
                    distance_bases = 0.0
                else:
                    distance_bases = max((b.distance_to(t) for b in observation.bases_taken), default=0.0)
                distance_self = u.distance_to(t)

                risk = distance_self + distance_bases
                reward = 1e-3 + distance_others * scout_value

                return risk / reward

            targets = distribute(
                overseers,
                observation.enemy_combatants,
                pairwise_distances(
                    [a.position for a in overseers],
                    [b.position for b in observation.enemy_combatants],
                ),
                lp=True,
            )
            for u in overseers:

                def scout_with_overseer() -> Action | None:
                    if target := targets.get(u):
                        target_point = observation.find_path(
                            start=u.position,
                            target=target.position,
                            air=True,
                        )
                        return Move(u, target_point)
                    return None

                if action := (
                    dodge.dodge_with(u)
                    or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                    or spawn_changeling(u)
                    or scout.actions.get(u)
                    or scout_with_overseer()
                    # or combat.advance_with(u)
                ):
                    yield action

        def micro_harvester(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                or resources.gather_with(u, observation.townhalls.ready)
                or (drone_scout(u) if observation.townhalls.ready.amount < 2 else search_with(u))
            )

        def micro_overlord(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                or scout.actions.get(u)
                or search_with(u)
            )

        def micro_unit(u: Unit) -> Action | None:
            unit_type = unit.type_id
            return (
                dodge.dodge_with(u)
                or (combat.do_burrow(u) if unit_type in {UnitTypeId.ROACH} else None)
                or (combat.do_unburrow(u) if unit_type in {UnitTypeId.ROACHBURROWED} else None)
                or (corrosive_biles.actions.get(u) if unit_type in {UnitTypeId.RAVAGER} else None)
                or (micro_queen(u) if unit_type in {UnitTypeId.QUEEN} else None)
                # or (
                #     combat.retreat_with(u)
                #     if combat.prediction.outcome == CombatOutcome.Defeat
                #     and not observation.bot.has_creep(u)
                #     and not observation.is_micro_map
                #     else None
                # )
                or combat.fight_with(u)
                or search_with(u)
            )

        def spawn_changeling(unit: Unit) -> Action | None:
            if not observation.pathing[unit.position.rounded]:
                return None
            elif unit.energy < ENERGY_COST[AbilityId.SPAWNCHANGELING_SPAWNCHANGELING]:
                return None
            return UseAbility(unit, AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)

        def drone_scout(unit: Unit) -> Action | None:
            if not (unit.is_idle or unit.is_gathering or unit.is_returning):
                return None
            if not (
                target_base := min(
                    filter(lambda b: not observation.is_visible(b), observation.bases),
                    key=lambda b: unit.distance_to(b),
                    default=None,
                )
            ):
                return None
            # target = unit.position.towards_with_random_angle(
            #     p=random.choice(observation.enemy_start_locations),
            #     distance=random.normalvariate(10, 10))
            target = observation.random_point(near=target_base)
            if observation.is_visible(target):
                return None
            if not observation.pathing[target.rounded]:
                return None
            return Move(unit, target)

        def search_with(unit: Unit) -> Action | None:
            if not (unit.is_idle or unit.is_gathering or unit.is_returning):
                return None
            elif observation.time < 8 * 60 and observation.enemy_start_locations:
                return Move(unit, random.choice(observation.enemy_start_locations))
            elif observation.enemy_combatants:
                target = cy_closest_to(unit.position, observation.enemy_combatants)
                return Move(unit, target.position)
            target = observation.random_point(near=unit.position)
            if observation.is_visible(target):
                return None
            if not observation.pathing[target.position.rounded] and not unit.is_flying:
                return None
            return Move(unit, target)

        for action in macro_actions.values():
            yield action
        for action in scout.actions.values():
            yield action
        for worker in harvesters:
            if a := micro_harvester(worker):
                yield a
        for tumor in creep.active_tumors:
            if a := creep.spread_with_tumor(tumor):
                yield a
        for action in micro_overseers(observation.overseers):
            yield action
        for unit in observation.units(UnitTypeId.OVERLORD):
            if a := micro_overlord(unit):
                yield a
        for unit in observation.units(CHANGELINGS):
            if a := search_with(unit):
                yield a
        for unit in observation.combatants:
            if unit in scout.actions:
                pass
            elif unit in macro_actions:
                pass
            else:
                if a := micro_unit(unit):
                    yield a
        for structure in observation.structures.not_ready:
            if structure.health_percentage < 0.1:
                yield UseAbility(structure, AbilityId.CANCEL)
