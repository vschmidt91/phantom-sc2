import math
import random
from dataclasses import dataclass
from itertools import chain
from typing import AsyncGenerator, Iterable

import numpy as np
from cython_extensions import cy_closest_to
from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.action import CombatAction
from bot.combat.dodge import DodgeState
from bot.combat.predictor import CombatOutcome
from bot.common.action import Action, DoNothing, Move, UseAbility
from bot.common.assignment import Assignment
from bot.common.constants import (
    ALL_MACRO_ABILITIES,
    CHANGELINGS,
    ENERGY_COST,
    GAS_BY_RACE,
)
from bot.common.main import BlockedPositions
from bot.corrosive_biles import CorrosiveBileState
from bot.macro.build_order import HATCH_FIRST, POOL_FIRST
from bot.macro.state import MacroPlan, MacroState
from bot.macro.strategy import Strategy
from bot.observation import Observation
from bot.queens.creep import CreepState
from bot.queens.inject import InjectState
from bot.queens.transfuse import transfuse_with
from bot.resources.action import ResourceAction
from bot.resources.observation import ResourceObservation
from bot.scout import Scout


@dataclass
class BotState:

    macro = MacroState()
    creep = CreepState()
    inject = InjectState()
    corrosive_biles = CorrosiveBileState()
    dodge = DodgeState()
    blocked_positions = BlockedPositions({})
    build_order = POOL_FIRST

    async def step(self, observation: Observation) -> AsyncGenerator[Action, None]:

        # Update blocked positions
        for error in observation.bot.state.action_errors:
            if (
                error.result == ActionResult.CantBuildLocationInvalid.value
                and error.ability_id == AbilityId.ZERGBUILD_HATCHERY.value
            ):
                if unit := observation.bot.unit_tag_dict.get(error.unit_tag):
                    p = unit.position.rounded
                    if p not in self.blocked_positions:
                        self.blocked_positions += {p: observation.bot.time}
                        logger.info(f"Detected blocked base {p}")
        for position, blocked_since in self.blocked_positions.items():
            if blocked_since + 60 < observation.bot.time:
                self.blocked_positions -= {position}

        bases = []
        scout_targets = list[Point2]()
        if not observation.is_micro_map:
            bases.extend(observation.bot.expansion_locations_list)
            bases_sorted = sorted(bases, key=lambda b: b.distance_to(observation.bot.start_location))
            scout_targets.extend(bases_sorted[1 : len(bases_sorted) // 2])
        for pos in bases:
            pos = 0.5 * (pos + observation.bot.start_location)
            scout_targets.insert(1, pos)
        scouts = observation.units({UnitTypeId.OVERLORD, UnitTypeId.OVERSEER})
        scouting = Scout(observation.bot, scouts, frozenset(scout_targets), frozenset(self.blocked_positions))

        strategy = Strategy(observation)

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

        combat = CombatAction(observation)
        creep = self.creep.step(observation, 0 <= combat.confidence)
        inject_actions = self.inject.step(observation.units(UnitTypeId.QUEEN), observation.townhalls.ready)
        dodge = self.dodge.step(observation)
        macro_actions = await self.macro.step(observation, set(self.blocked_positions), combat)

        should_inject = observation.bot.supply_used + observation.bot.larva.amount < 200
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
            p = r.position.rounded
            return 0 <= combat.confidence[p] or 0 == combat.enemy_presence.dps[p]

        harvesters = observation.workers.filter(should_harvest)

        if observation.is_micro_map:
            resources_to_harvest = Units([], observation.bot)
            gas_ratio = 0.0
        else:
            resources_to_harvest = observation.all_taken_resources.filter(should_harvest_resource)

            required = observation.bot.cost.zero
            required += sum(
                (observation.bot.cost.of(plan.item) for plan in self.macro.unassigned_plans), observation.bot.cost.zero
            )
            required += sum(
                (observation.bot.cost.of(plan.item) for plan in self.macro.assigned_plans.values()),
                observation.bot.cost.zero,
            )
            required += observation.bot.cost.of_composition(strategy.composition_deficit)
            required -= observation.bank

            if required.minerals <= 0 and required.vespene <= 0:
                optimal_gas_ratio = 1.0
            else:
                mineral_trips = max(0.0, required.minerals / 5)
                vespene_trips = max(0.0, required.vespene / 4)
                optimal_gas_ratio = vespene_trips / (mineral_trips + vespene_trips)
            gas_ratio = optimal_gas_ratio

        resources = ResourceAction(
            ResourceObservation(
                observation,
                harvesters,
                observation.bot.gas_buildings.ready,
                resources_to_harvest.vespene_geyser,
                resources_to_harvest.mineral_field,
                gas_ratio,
            )
        )

        gas_type = GAS_BY_RACE[observation.bot.race]
        gas_depleted = observation.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = observation.count(gas_type, include_actual=False)
        gas_have = resources.observation.gas_buildings.amount
        gas_max = resources.observation.vespene_geysers.amount
        gas_want = min(gas_max, gas_depleted + math.ceil((resources.gas_target - 1) / 3))
        if gas_have + gas_pending < gas_want:
            self.macro.add(MacroPlan(gas_type))

        corrosive_biles = self.corrosive_biles.step(observation)

        def micro_queen(q: Unit) -> Action | None:
            return (
                transfuse_with(q, observation.units)
                or (combat.fight_with(q) if 0 < combat.enemy_presence.dps[q.position.rounded] else None)
                or (inject_actions.get(q) if should_inject else None)
                or (creep.spread_with_queen(q) if should_spread_creep else None)
                or (combat.retreat_with(q) if not observation.bot.has_creep(q) else None)
                or combat.fight_with(q)
            )

        def micro_overseers(overseers: Units) -> Iterable[Action]:

            def cost(u: Unit, t: Unit) -> float:
                scout_cost = 1.0 if t.is_burrowed or t.is_cloaked else 100.0
                distance_others = sum(v.distance_to(t) for v in overseers) / len(overseers)
                distance_self = u.distance_to(t)
                return scout_cost * distance_self / max(1.0, distance_others)

            targets = Assignment.distribute(
                overseers,
                observation.enemy_units,
                cost,
            )
            for u in overseers:

                def scout() -> Action | None:
                    if target := targets.get(u):
                        target_point = observation.bot.mediator.find_path_next_point(
                            start=u.position,
                            target=target.position,
                            grid=observation.bot.mediator.get_air_avoidance_grid,
                        )
                        return Move(u, target_point)
                    return None

                if action := (
                    dodge.dodge_with(u)
                    or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                    or spawn_changeling(u)
                    or scout_actions.get(u)
                    or scout()
                    # or combat.advance_with(u)
                ):
                    yield action

        def micro_harvester(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                or resources.gather_with(u, observation.townhalls.ready)
            )

        def micro_overlord(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                or scout_actions.get(u)
                or search_with(u)
            )

        def micro_unit(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.do_burrow(u) if u.type_id in {UnitTypeId.ROACH, UnitTypeId.RAVAGER} else None)
                or (combat.do_unburrow(u) if u.type_id in {UnitTypeId.ROACHBURROWED, UnitTypeId.RAVAGERBURROWED} else None)
                or (corrosive_biles.actions.get(u) if u.type_id in {UnitTypeId.RAVAGER} else None)
                or (micro_queen(u) if unit.type_id in {UnitTypeId.QUEEN} else None)
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
            if not observation.bot.in_pathing_grid(unit):
                return None
            elif unit.energy < ENERGY_COST[AbilityId.SPAWNCHANGELING_SPAWNCHANGELING]:
                return None
            return UseAbility(unit, AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)

        def search_with(unit: Unit) -> Action | None:
            if not unit.is_idle:
                return None
            elif observation.bot.time < 8 * 60 and observation.enemy_start_locations:
                return Move(unit, random.choice(observation.enemy_start_locations))
            elif observation.enemy_units:
                target = cy_closest_to(unit.position, observation.enemy_units)
                return Move(unit, target.position)
            a = observation.bot.game_info.playable_area
            target = Point2(np.random.uniform((a.x, a.y), (a.right, a.top)))
            if observation.bot.is_visible(target):
                return None
            if not observation.bot.in_pathing_grid(target) and not unit.is_flying:
                return None
            return Move(unit, target)

        scout_actions = scouting.get_actions()
        for action in macro_actions.values():
            yield action
        for action in scout_actions.values():
            yield action
        for worker in harvesters:
            yield micro_harvester(worker) or DoNothing()
        for tumor in creep.active_tumors:
            yield creep.spread_with_tumor(tumor) or DoNothing()
        for action in micro_overseers(observation.overseers):
            yield action
        for unit in observation.units(UnitTypeId.OVERLORD):
            yield micro_overlord(unit) or DoNothing()
        for unit in observation.units(CHANGELINGS):
            yield search_with(unit) or DoNothing()
        for unit in observation.units:
            if unit in scout_actions:
                pass
            elif unit in macro_actions:
                pass
            else:
                yield micro_unit(unit) or DoNothing()
        for structure in observation.structures.not_ready:
            if structure.health_percentage < 0.1:
                yield UseAbility(structure, AbilityId.CANCEL)
