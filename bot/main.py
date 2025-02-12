import math
import os
import random
from itertools import chain
from typing import AsyncGenerator, Iterable

import numpy as np
from ares import DEBUG
from cython_extensions import cy_closest_to
from loguru import logger
from sc2.data import ActionResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.action import CombatAction
from bot.combat.dodge import DodgeState
from bot.common.action import Action, DoNothing, Move, UseAbility
from bot.common.assignment import Assignment
from bot.common.constants import (
    ALL_MACRO_ABILITIES,
    CHANGELINGS,
    ENERGY_COST,
    GAS_BY_RACE,
    REQUIREMENTS,
    VERSION_FILE,
    WITH_TECH_EQUIVALENTS,
)
from bot.common.cost import CostManager
from bot.common.main import BlockedPositions, BotBase
from bot.common.unit_composition import UnitComposition
from bot.corrosive_biles import CorrosiveBile
from bot.debug import Debug
from bot.macro.build_order import HATCH_FIRST
from bot.macro.state import MacroId, MacroPlan, MacroState
from bot.macro.strategy import Strategy
from bot.observation import Observation
from bot.queens.creep import CreepState
from bot.queens.inject import InjectState
from bot.queens.transfuse import transfuse_with
from bot.resources.action import ResourceAction
from bot.resources.observation import HarvesterAssignment, ResourceObservation
from bot.resources.state import ResourceState
from bot.scout import Scout


class PhantomBot(BotBase):

    debug: Debug | None = None
    dodge = DodgeState()
    corrosive_biles = CorrosiveBile()
    planner = MacroState()
    creep = CreepState()
    inject = InjectState()
    resource_state = ResourceState(HarvesterAssignment({}))
    blocked_positions = BlockedPositions({})
    build_order = HATCH_FIRST
    replay_tags = set[str]()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cost = CostManager(self)

    # CALLBACKS ========================================================================================================
    # vvvvvvvvv

    async def on_start(self) -> None:
        await super().on_start()

        if self.config[DEBUG]:
            self.debug = Debug(self)
            await self.debug.on_start()

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                await self.add_replay_tag(f"version_{f.read()}")

    async def on_step(self, iteration: int):
        if iteration == 0:
            if self.config[DEBUG]:  # local only: skip first iteration like on the ladder
                return
        if self.debug:
            await self.debug.on_step_start()
        await super().on_step(iteration)

        observation = Observation(self)
        strategy = Strategy(observation)
        actions = [a async for a in self.micro(observation, strategy)]
        if build_order := self.build_order.execute(observation):
            actions.extend(build_order.actions)
            for plan in build_order.plans:
                self.planner.add(plan)
        else:
            for plan in self.macro(observation, strategy):
                self.planner.add(plan)
        for action in actions:
            success = await action.execute(self)
            if not success:
                await self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        if self.debug:
            await self.debug.on_step_end()

    # async def on_before_start(self):
    #     await super().on_before_start()
    #
    # async def on_end(self, game_result: Result):
    #     await super().on_end(game_result)
    #
    # async def on_building_construction_started(self, unit: Unit):
    #     await super().on_building_construction_started(unit)
    #
    # async def on_building_construction_complete(self, unit: Unit):
    #     await super().on_building_construction_complete(unit)
    #
    # async def on_enemy_unit_entered_vision(self, unit: Unit):
    #     await super().on_enemy_unit_entered_vision(unit)
    #
    # async def on_enemy_unit_left_vision(self, unit_tag: int):
    #     await super().on_enemy_unit_left_vision(unit_tag)
    #
    # async def on_unit_destroyed(self, unit_tag: int):
    #     await super().on_unit_destroyed(unit_tag)
    #
    # async def on_unit_created(self, unit: Unit):
    #     await super().on_unit_created(unit)
    #
    # async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
    #     await super().on_unit_type_changed(unit, previous_type)
    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
    #     await super().on_unit_took_damage(unit, amount_damage_taken)
    #
    # async def on_upgrade_complete(self, upgrade: UpgradeId):
    #     await super().on_upgrade_complete(upgrade)

    # ^^^^^^^^^^
    # CALLBACKS ========================================================================================================

    async def add_replay_tag(self, tag: str) -> None:
        if tag not in self.replay_tags:
            self.replay_tags.add(tag)
            await self.client.chat_send(f"Tag:{tag}", True)

    def macro(self, observation: Observation, strategy: Strategy) -> Iterable[MacroPlan]:
        return chain(
            self.make_composition(observation, strategy.composition_target),
            self.make_tech(observation, strategy),
            self.morph_overlord(observation),
            self.expand(observation),
        )

    def optimal_gas_ratio(self, observation: Observation, composition: UnitComposition) -> float:
        required = self.cost.zero
        required += self.planner.get_total_cost(self.cost)
        required += self.cost.of_composition(composition)
        required -= observation.bank

        if required.minerals <= 0 and required.vespene <= 0:
            return 1.0
        mineral_trips = max(0.0, required.minerals / 5)
        vespene_trips = max(0.0, required.vespene / 4)
        gas_ratio = vespene_trips / (mineral_trips + vespene_trips)
        return gas_ratio

    def get_scouting(self, blocked_positions: BlockedPositions) -> Scout:
        bases = []
        scout_targets = list[Point2]()
        if not self.is_micro_map:
            bases.extend(self.expansion_locations_list)
            bases_sorted = sorted(bases, key=lambda b: b.distance_to(self.start_location))
            scout_targets.extend(bases_sorted[1 : len(bases_sorted) // 2])
        for pos in bases:
            pos = 0.5 * (pos + self.start_location)
            scout_targets.insert(1, pos)
        scouts = self.units({UnitTypeId.OVERLORD, UnitTypeId.OVERSEER})
        return Scout(self, scouts, frozenset(scout_targets), frozenset(blocked_positions))

    async def micro(
        self,
        observation: Observation,
        strategy: Strategy,
    ) -> AsyncGenerator[Action, None]:

        combat = CombatAction(observation, strategy)

        creep = self.creep.step(observation, 0 <= combat.confidence)
        inject = self.inject.step(self.units(UnitTypeId.QUEEN), self.townhalls.ready)
        should_inject = self.supply_used + self.larva.amount < 200
        should_spread_creep = self.creep.unspread_tumor_count < 10

        self.update_blocked_positions()
        planned_actions = await self.planner.get_actions(observation, set(self.blocked_positions), combat)

        def should_harvest(u: Unit) -> bool:
            if self.is_micro_map:
                return False
            elif u in planned_actions:  # got special orders?
                return False
            elif u.is_idle:  # you slackin?
                return True
            elif u.orders[0].ability.exact_id in ALL_MACRO_ABILITIES:
                return False  # alright, carry on!
            return True  # get on with it!

        def should_harvest_resource(r: Unit) -> bool:
            p = r.position.rounded
            return 0 <= combat.confidence[p] or 0 == combat.enemy_presence.dps[p]

        harvesters = self.workers.filter(should_harvest)

        if self.is_micro_map:
            resources_to_harvest = Units([], self)
            gas_ratio = 0.0
        else:
            resources_to_harvest = observation.all_taken_resources.filter(should_harvest_resource)
            gas_ratio = self.optimal_gas_ratio(observation, strategy.composition_deficit)
        resource_observation = ResourceObservation(
            observation,
            harvesters,
            self.gas_buildings.ready,
            resources_to_harvest.vespene_geyser,
            resources_to_harvest.mineral_field,
            gas_ratio,
        )
        resource_action = self.resource_state.step(resource_observation)
        for plan in self.build_gasses(observation, resource_action):
            self.planner.add(plan)

        dodge = self.dodge.step(observation)

        corrosive_biles = self.corrosive_biles.step(observation)

        def micro_queen(q: Unit) -> Action | None:
            return (
                transfuse_with(q, observation.units)
                or (combat.fight_with(q) if 0 < combat.enemy_presence.dps[q.position.rounded] else None)
                or (inject.get(q) if should_inject else None)
                or (creep.spread_with_queen(q) if should_spread_creep else None)
                or (combat.retreat_with(q) if not self.has_creep(q) else None)
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
                        target_point = self.mediator.find_path_next_point(
                            start=u.position,
                            target=target.position,
                            grid=self.mediator.get_air_avoidance_grid,
                        )
                        return Move(u, target_point)
                    return None

                if action := (
                    dodge.dodge_with(u)
                    or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                    or self.do_spawn_changeling(u)
                    or scout_actions.get(u)
                    or scout()
                    # or combat.advance_with(u)
                ):
                    yield action

        def micro_harvester(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                or resource_action.gather_with(u, self.townhalls.ready)
            )

        def micro_overlord(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.retreat_with(u) if combat.confidence[u.position.rounded] < 0 else None)
                or scout_actions.get(u)
                or self.search_with(u)
            )

        def micro_unit(u: Unit) -> Action | None:
            return (
                dodge.dodge_with(u)
                or (combat.do_burrow(u) if u.type_id in {UnitTypeId.ROACH} else None)
                or (combat.do_unburrow(u) if u.type_id in {UnitTypeId.ROACHBURROWED} else None)
                or (corrosive_biles.actions.get(u) if u.type_id in {UnitTypeId.RAVAGER} else None)
                or (micro_queen(u) if unit.type_id in {UnitTypeId.QUEEN} else None)
                or combat.fight_with(u)
                or self.search_with(u)
            )

        scout_actions = self.get_scouting(self.blocked_positions).get_actions()

        for action in planned_actions.values():
            yield action
        for action in scout_actions.values():
            yield action
        for worker in harvesters:
            yield micro_harvester(worker) or DoNothing()
        for tumor in creep.active_tumors:
            yield creep.spread_with_tumor(tumor) or DoNothing()
        for action in micro_overseers(self.units(UnitTypeId.OVERSEER)):
            yield action
        for unit in self.units(UnitTypeId.OVERLORD):
            yield micro_overlord(unit) or DoNothing()
        for unit in self.units(CHANGELINGS):
            yield self.search_with(unit) or DoNothing()
        for unit in observation.units:
            if unit in scout_actions:
                pass
            elif unit in planned_actions:
                pass
            else:
                yield micro_unit(unit) or DoNothing()
        for structure in self.structures.not_ready:
            if structure.health_percentage < 0.1:
                yield UseAbility(structure, AbilityId.CANCEL)

    def build_gasses(self, observation: Observation, resources: ResourceAction) -> Iterable[MacroPlan]:
        gas_type = GAS_BY_RACE[self.race]
        gas_depleted = self.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = observation.count(gas_type, include_actual=False)
        gas_have = resources.observation.gas_buildings.amount
        gas_max = resources.observation.vespene_geysers.amount
        gas_want = min(gas_max, gas_depleted + math.ceil((resources.gas_target - 1) / 3))
        if gas_have + gas_pending < gas_want:
            yield MacroPlan(gas_type)

    def planned_by_type(self, item: MacroId) -> Iterable:
        return self.planner.planned_by_type(item)

    def search_with(self, unit: Unit) -> Action | None:
        if not unit.is_idle:
            return None
        elif self.time < 8 * 60:
            return Move(unit, random.choice(self.enemy_start_locations))
        elif self.all_enemy_units:
            target = cy_closest_to(unit.position, self.all_enemy_units)
            return Move(unit, target.position)
        a = self.game_info.playable_area
        target = Point2(np.random.uniform((a.x, a.y), (a.right, a.top)))
        if self.is_visible(target):
            return None
        if not self.in_pathing_grid(target) and not unit.is_flying:
            return None
        return Move(unit, target)

    def update_blocked_positions(self) -> None:
        for error in self.state.action_errors:
            if (
                error.result == ActionResult.CantBuildLocationInvalid.value
                and error.ability_id == AbilityId.ZERGBUILD_HATCHERY.value
            ):
                if unit := self.unit_tag_dict.get(error.unit_tag):
                    p = unit.position.rounded
                    if p not in self.blocked_positions:
                        self.blocked_positions += {p: self.time}
                        logger.info(f"Detected blocked base {p}")
        for position, blocked_since in self.blocked_positions.items():
            if blocked_since + 60 < self.time:
                self.blocked_positions -= {position}

    def make_composition(self, observation: Observation, composition: UnitComposition) -> Iterable[MacroPlan]:
        if 200 <= self.supply_used:
            return
        for unit in composition:
            target = composition[unit]
            have = observation.count(unit)
            if target < 1:
                continue
            elif target <= have:
                continue
            if any(observation.get_missing_requirements(unit)):
                continue
            priority = -observation.count(unit, include_planned=False) / target
            if any(self.planned_by_type(unit)):
                for plan in self.planned_by_type(unit):
                    if plan.priority == math.inf:
                        continue
                    plan.priority = priority
                    break
            else:
                yield MacroPlan(unit, priority=priority)

    def make_tech(self, observation: Observation, strategy: Strategy) -> Iterable[MacroPlan]:
        upgrades = [
            u
            for unit, count in strategy.composition_target.items()
            for u in observation.upgrades_by_unit(unit)
            if strategy.filter_upgrade(u)
        ]
        upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        targets: set[MacroId] = set(upgrades)
        targets.update(strategy.composition_target.keys())
        targets.update(r for item in set(targets) for r in REQUIREMENTS[item])
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(observation.count(t) for t in equivalents)
            else:
                target_met = bool(observation.count(target))
            if not target_met:
                yield MacroPlan(target, priority=-0.5)

    def morph_overlord(self, observation: Observation) -> Iterable[MacroPlan]:
        supply = self.supply_cap + observation.supply_pending / 2 + observation.supply_planned
        supply_target = min(200.0, self.supply_used + 2 + 20 * observation.income.larva)
        if supply_target <= supply:
            return
        yield MacroPlan(UnitTypeId.OVERLORD, priority=1)

    def expand(self, observation: Observation) -> Iterable[MacroPlan]:

        if self.time < 50:
            return
        if 2 == self.townhalls.amount and 2 > observation.count(UnitTypeId.QUEEN, include_planned=False):
            return

        worker_max = observation.max_harvesters
        saturation = max(0, min(1, self.state.score.food_used_economy / max(1, worker_max)))
        if 2 < self.townhalls.amount and 4 / 5 > saturation:
            return

        priority = 5 * (saturation - 1)
        for plan in self.planned_by_type(UnitTypeId.HATCHERY):
            if plan.priority < math.inf:
                plan.priority = priority

        if 0 < observation.count(UnitTypeId.HATCHERY, include_actual=False):
            return
        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority, max_distance=None)

    def do_spawn_changeling(self, unit: Unit) -> Action | None:
        if not self.in_pathing_grid(unit):
            return None
        elif unit.energy < ENERGY_COST[AbilityId.SPAWNCHANGELING_SPAWNCHANGELING]:
            return None
        return UseAbility(unit, AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)
