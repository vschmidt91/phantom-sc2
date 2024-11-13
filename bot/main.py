import math
import os
import random
from itertools import chain
from typing import AsyncGenerator, Iterable

import numpy as np
from ares import DEBUG
from loguru import logger
from sc2.data import ActionResult, Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.common.action import Action, AttackMove, DoNothing, UseAbility
from bot.common.constants import (
    ALL_MACRO_ABILITIES,
    CHANGELINGS,
    CIVILIANS,
    ENERGY_COST,
    GAS_BY_RACE,
    REQUIREMENTS,
    UNKNOWN_VERSION,
    VERSION_FILE,
    WITH_TECH_EQUIVALENTS,
)
from bot.common.main import BotBase
from bot.common.unit_composition import UnitComposition
from bot.components.combat.corrosive_biles import CorrosiveBiles
from bot.components.combat.dodge import Dodge, DodgeResult
from bot.components.combat.main import Combat
from bot.components.combat.scout import Scout
from bot.components.macro.build_order import HATCH_FIRST
from bot.components.macro.planner import MacroId, MacroPlan, MacroPlanner
from bot.components.macro.strategy import Strategy
from bot.components.queens.creep import CreepSpread
from bot.components.queens.inject import Inject
from bot.components.queens.transfuse import do_transfuse_single
from bot.components.resources.main import (
    HarvesterAssignment,
    ResourceContext,
    ResourceReport,
    update_resources,
)
from bot.debug import Debug, DebugBase, DebugDummy


class PhantomBot(BotBase):

    creep = CreepSpread()
    inject = Inject()
    dodge = Dodge()
    corrosive_biles = CorrosiveBiles()
    planner = MacroPlanner()
    _debug: DebugBase = DebugDummy()
    build_order = HATCH_FIRST
    harvester_assignment = HarvesterAssignment({})
    version = UNKNOWN_VERSION
    _blocked_positions = dict[Point2, float]()
    _replay_tags = set[str]()
    _max_harvesters = 16

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def on_before_start(self):
        await super().on_before_start()

    async def on_start(self) -> None:
        await super().on_start()

        if self.config[DEBUG]:
            self._debug = Debug(self)
            await self._debug.on_start()

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                await self.add_replay_tag(f"version_{f.read()}")

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        if self.config[DEBUG]:
            if iteration == 0:  # local only: skip first iteration like on the ladder
                return

        await self._debug.on_step_start()

        self.update_blocked_bases()
        strategy = Strategy(
            context=self, max_harvesters=max(1, min(80, self._max_harvesters))  # TODO: exclude mined out resources,
        )
        for plan in self.macro(strategy):
            self.planner.add(plan)
        async for action in self.micro(strategy):
            success = await action.execute(self)
            if not success:
                await self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        await self._debug.on_step_end()

    async def on_end(self, game_result: Result):
        await super().on_end(game_result)

    async def on_building_construction_started(self, unit: Unit):
        await super().on_building_construction_started(unit)

    async def on_building_construction_complete(self, unit: Unit):
        await super().on_building_construction_complete(unit)

    async def on_enemy_unit_entered_vision(self, unit: Unit):
        await super().on_enemy_unit_entered_vision(unit)

    async def on_enemy_unit_left_vision(self, unit_tag: int):
        await super().on_enemy_unit_left_vision(unit_tag)

    async def on_unit_destroyed(self, unit_tag: int):
        await super().on_unit_destroyed(unit_tag)

    async def on_unit_created(self, unit: Unit):
        await super().on_unit_created(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        await super().on_unit_type_changed(unit, previous_type)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        await super().on_unit_took_damage(unit, amount_damage_taken)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        await super().on_upgrade_complete(upgrade)

    async def add_replay_tag(self, tag: str) -> None:
        if tag not in self._replay_tags:
            self._replay_tags.add(tag)
            await self.client.chat_send(f"Tag:{tag}", True)

    def macro(self, strategy: Strategy) -> Iterable[MacroPlan]:
        build_order_actions = self.run_build_order()
        if build_order_actions is not None:
            return build_order_actions
        return chain(
            self.make_composition(strategy.composition_target),
            self.make_tech(strategy),
            self.morph_overlord(),
            self.expand(),
        )

    def optimal_gas_ratio(self, composition: UnitComposition) -> float:
        required = self.cost.zero
        required += self.planner.get_total_cost(self.cost)
        required += self.cost.of_composition(composition)
        required -= self.bank
        mineral_trips = required.minerals / 5
        vespene_trips = required.vespene / 4
        gas_ratio = vespene_trips / max(1.0, mineral_trips + vespene_trips)
        return gas_ratio

    def get_scouting(self) -> Scout:
        bases_sorted = sorted(self.expansion_locations_list, key=lambda b: b.distance_to(self.start_location))
        scout_targets = bases_sorted[1 : len(bases_sorted) // 2]
        for pos in self.enemy_start_locations:
            pos = 0.5 * (pos + self.start_location)
            scout_targets.insert(1, pos)
        scouts = self.units({UnitTypeId.OVERLORD, UnitTypeId.OVERSEER})
        return Scout(self, scouts, frozenset(scout_targets), frozenset(self._blocked_positions))

    async def micro(
        self,
        strategy: Strategy,
    ) -> AsyncGenerator[Action, None]:

        combat = Combat(
            bot=self,
            strategy=strategy,
            units=self.units.exclude_type(CIVILIANS),
            enemy_units=self.all_enemy_units.exclude_type(CIVILIANS),
            dps=self.dps_fast,
            pathing=self.mediator.get_map_data_object.get_pyastar_grid(),
            air_pathing=self.mediator.get_map_data_object.get_clean_air_grid(),
            retreat_targets=frozenset([s.position for s in self.structures] + [self.start_location]),
            attack_targets=frozenset([p.position for p in self.all_enemy_units] + self.enemy_start_locations),
        )

        creep = self.creep.update(self)
        queens = self.units(UnitTypeId.QUEEN)
        self.inject.assign(queens, self.townhalls.ready)
        should_inject = self.supply_used + self.larva.amount < 200
        should_spread_creep = self.creep.active_tumor_count < 10
        planned_actions = await self.planner.get_actions(self, set(self._blocked_positions))

        def should_harvest(u: Unit) -> bool:
            if u in planned_actions:  # got special orders?
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
        resources_to_harvest = self.all_taken_resources.filter(should_harvest_resource)
        gas_ratio = self.optimal_gas_ratio(strategy.composition_deficit)
        resource_context = ResourceContext(
            self,
            self.harvester_assignment,
            harvesters,
            self.gas_buildings.ready,
            resources_to_harvest.vespene_geyser,
            resources_to_harvest.mineral_field,
            gas_ratio,
        )
        resource_report = update_resources(resource_context)
        self.harvester_assignment = resource_report.assignment
        self._max_harvesters = resource_context.max_harvesters
        for plan in self.build_gasses(resource_report):
            self.planner.add(plan)

        dodge = self.dodge.update(self)

        def micro_queen(q: Unit) -> Action | None:
            return (
                dodge.dodge_with(q)
                or do_transfuse_single(q, combat.units)
                or (self.inject.inject_with(q) if should_inject else None)
                or (creep.spread_with_queen(q) if should_spread_creep else None)
                or (combat.retreat_with(q) if not self.has_creep(q) else None)
                or combat.fight_with(q)
                # or DoNothing()
            )

        def micro_unit(unit: Unit) -> Action | None:
            return (
                dodge.dodge_with(unit)
                or (self.do_spawn_changeling(unit) if unit.type_id in {UnitTypeId.OVERSEER} else None)
                or (self.search_with(unit) if unit.type_id in CHANGELINGS else None)
                or (combat.do_burrow(unit) if unit.type_id in {UnitTypeId.ROACH} else None)
                or (combat.do_unburrow(unit) if unit.type_id in {UnitTypeId.ROACHBURROWED} else None)
                or (self.corrosive_biles.get_action(self, unit) if unit.type_id in {UnitTypeId.RAVAGER} else None)
                or (micro_queen(unit) if unit.type_id in {UnitTypeId.QUEEN} else None)
                or (combat.fight_with(unit) if unit.type_id not in CIVILIANS else None)
                or self.search_with(unit)
            )

        scout_actions = self.get_scouting().get_actions()

        for worker in harvesters:
            yield self.micro_harvester(worker, combat, dodge, resource_report) or DoNothing()
        for action in planned_actions.values():
            yield action
        for tumor in self.creep.get_active_tumors(self):
            yield creep.spread_with_tumor(tumor) or DoNothing()
        for unit in combat.units:
            if unit in scout_actions:
                pass
            elif unit in planned_actions:
                pass
            else:
                yield micro_unit(unit) or DoNothing()
        for action in scout_actions.values():
            yield action

    def build_gasses(self, resources: ResourceReport) -> Iterable[MacroPlan]:
        gas_type = GAS_BY_RACE[self.race]
        gas_depleted = self.gas_buildings.filter(lambda g: not g.has_vespene).amount
        gas_pending = self.count(gas_type, include_actual=False)
        gas_have = resources.context.gas_buildings.amount
        gas_max = resources.context.vespene_geysers.amount
        gas_want = min(gas_max, gas_depleted + math.ceil((resources.gas_target - 1) / 3))
        if gas_have + gas_pending < gas_want:
            yield MacroPlan(gas_type)

    def planned_by_type(self, item: MacroId) -> Iterable:
        return self.planner.planned_by_type(item)

    def micro_harvester(
        self, unit: Unit, combat: Combat, dodge: DodgeResult, resources: ResourceReport
    ) -> Action | None:
        return dodge.dodge_with(unit) or resources.gather_with(unit, self.townhalls.ready) or combat.fight_with(unit)

    def run_build_order(self) -> list[MacroPlan] | None:
        for i, step in enumerate(self.build_order.steps):
            if self.count(step.unit, include_planned=False) >= step.count:
                pass
            elif self.count(step.unit) < step.count:
                return [MacroPlan(step.unit, priority=-i)]
            else:
                return []
        return None

    def search_with(self, unit: Unit) -> Action | None:
        if unit.is_idle and unit.type_id not in {UnitTypeId.QUEEN}:
            if self.time < 8 * 60:
                return AttackMove(unit, random.choice(self.enemy_start_locations))
            elif self.all_enemy_units.exists:
                target = self.all_enemy_units.random
                return AttackMove(unit, target.position)
            else:
                a = self.game_info.playable_area
                target = np.random.uniform((a.x, a.y), (a.right, a.top))
                target = Point2(target)
                if (unit.is_flying or self.in_pathing_grid(target)) and not self.is_visible(target):
                    return AttackMove(unit, target)
        return None

    def update_blocked_bases(self) -> None:
        for error in self.state.action_errors:
            if (
                error.result == ActionResult.CantBuildLocationInvalid.value
                and error.ability_id == AbilityId.ZERGBUILD_HATCHERY.value
            ):
                if unit := self.unit_tag_dict.get(error.unit_tag):
                    p = unit.position.rounded
                    if p not in self._blocked_positions:
                        self._blocked_positions[p] = self.time
                        logger.info(f"Detected blocked base {p}")
        for position, blocked_since in list(self._blocked_positions.items()):
            if blocked_since + 60 < self.time:
                del self._blocked_positions[position]

    def make_composition(self, composition: UnitComposition) -> Iterable[MacroPlan]:
        if 200 <= self.supply_used:
            return
        for unit in composition:
            target = composition[unit]
            have = self.count(unit)
            if target < 1:
                continue
            elif target <= have:
                continue
            if any(self.get_missing_requirements(unit)):
                continue
            priority = -self.count(unit, include_planned=False) / target
            if any(self.planned_by_type(unit)):
                for plan in self.planned_by_type(unit):
                    if plan.priority == math.inf:
                        continue
                    plan.priority = priority
                    break
            else:
                yield MacroPlan(unit, priority=priority)

    def make_tech(self, strategy: Strategy) -> Iterable[MacroPlan]:
        upgrades = [
            u
            for unit, count in strategy.composition_target.items()
            for u in self.upgrades_by_unit(unit)
            if strategy.filter_upgrade(u)
        ]
        upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        targets: set[MacroId] = set(upgrades)
        targets.update(strategy.composition_target.keys())
        targets.update(r for item in set(targets) for r in REQUIREMENTS[item])
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(self.count(t) for t in equivalents)
            else:
                target_met = bool(self.count(target))
            if not target_met:
                yield MacroPlan(target, priority=-0.5)

    def morph_overlord(self) -> Iterable[MacroPlan]:
        supply = self.supply_cap + self.supply_pending / 2 + self.supply_planned
        supply_target = min(200.0, self.supply_used + 2 + 20 * self.income.larva)
        if supply_target <= supply:
            return
        yield MacroPlan(UnitTypeId.OVERLORD, priority=1)

    def expand(self) -> Iterable[MacroPlan]:

        if self.time < 50:
            return
        if 2 == self.townhalls.amount and 2 > self.count(UnitTypeId.QUEEN, include_planned=False):
            return

        worker_max = self._max_harvesters
        saturation = max(0, min(1, self.state.score.food_used_economy / max(1, worker_max)))
        if 2 < self.townhalls.amount and 3 / 4 > saturation:
            return

        priority = 4 * (saturation - 1)
        for plan in self.planned_by_type(UnitTypeId.HATCHERY):
            if plan.priority < math.inf:
                plan.priority = priority

        if 0 < self.count(UnitTypeId.HATCHERY, include_actual=False):
            return
        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority, max_distance=None)

    def do_spawn_changeling(self, unit: Unit) -> Action | None:
        if not self.in_pathing_grid(unit):
            return None
        elif unit.energy < ENERGY_COST[AbilityId.SPAWNCHANGELING_SPAWNCHANGELING]:
            return None
        return UseAbility(unit, AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)
