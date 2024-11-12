import cProfile
import math
import os
import pstats
import random
from collections import defaultdict
from itertools import chain
from typing import AsyncGenerator, Iterable, cast

import numpy as np
from ares import DEBUG
from bot.common.unit_composition import UnitComposition
from loguru import logger
from sc2.data import ActionResult, Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bot.common.action import (
    Action,
    AttackMove,
    DoNothing,
    HoldPosition,
    Move,
    UseAbility,
)
from bot.common.base import BotBase
from bot.common.constants import (
    ALL_MACRO_ABILITIES,
    CHANGELINGS,
    CIVILIANS,
    COOLDOWN,
    ENERGY_COST,
    GAS_BY_RACE,
    REQUIREMENTS,
    UNKNOWN_VERSION,
    VERSION_FILE,
    WITH_TECH_EQUIVALENTS,
)
from bot.components.combat.combat import HALF, Combat
from bot.components.combat.dodge import Dodge, DodgeResult
from bot.components.combat.predictor import Prediction, PredictorContext, predict
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


class PhantomBot(BotBase):
    creep = CreepSpread()
    inject = Inject()
    dodge = Dodge()

    planner = MacroPlanner()
    build_order = HATCH_FIRST

    scout = Scout()
    harvester_assignment = HarvesterAssignment({})
    profiler = cProfile.Profile()
    version = UNKNOWN_VERSION
    _blocked_positions = dict[Point2, float]()
    _bile_last_used = dict[int, int]()
    _replay_tags = set[str]()
    _max_harvesters = 16

    async def on_before_start(self):
        await super().on_before_start()

    async def on_start(self) -> None:
        await super().on_start()
        # if self.config[DEBUG]:
        # output_path = os.path.join("resources", f"{self.game_info.map_name}.xz")
        # with lzma.open(output_path, "wb") as f:
        #     pickle.dump(self.game_info, f)
        # await self.client.debug_create_unit([[UnitTypeId.CREEPTUMORBURROWED, 1, self.bases[1].position, 2]])
        # await self.client.debug_create_unit(
        #     [
        #         [UnitTypeId.ROACH, 10, self.bases[1].position, 1],
        #         [UnitTypeId.ROACH, 10, self.bases[2].position, 2],
        #     ]
        # )
        # await self.client.debug_upgrade()
        self.scout.initialize_scout_targets(self, self.expansion_locations_list)

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                version = f.read()
                await self.add_replay_tag(f"version_{version}")

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        if self.config[DEBUG]:
            # local only: skip first iteration like on the ladder
            if iteration == 0:
                return
            self.profiler.enable()

        # ACTION HANDLING
        # -------------------------
        self.detect_blocked_bases()
        for error in self.state.action_errors:
            logger.info(f"{error=}")
        # ------------------------

        self.reset_blocked_bases()

        army = self.units.exclude_type(CIVILIANS)
        enemies = self.all_enemy_units.exclude_type(CIVILIANS)
        predictor_context = PredictorContext(
            units=army,
            enemy_units=enemies,
            dps=self.dps_fast,
            pathing=self.mediator.get_map_data_object.get_pyastar_grid(),
            air_pathing=self.mediator.get_map_data_object.get_clean_air_grid(),
        )
        prediction = predict(predictor_context)
        max_harvesters = max(1, min(80, self._max_harvesters))  # TODO: exclude mined out resources
        strategy = Strategy(
            context=self,
            confidence=prediction.confidence_global,
            max_harvesters=max_harvesters,
            enemies=enemies,
        )

        target_units = {u for u, n in strategy.composition_target.items() if n > 0}
        upgrades = {u for unit in target_units for u in self.upgrades_by_unit(unit) if strategy.filter_upgrade(u)}
        upgrades.add(UpgradeId.ZERGLINGMOVEMENTSPEED)
        tech_targets = set(target_units) | set(upgrades)

        if self.run_build_order():
            if plan := (
                self.make_composition(strategy.composition_target)
                or self.make_tech(strategy)
                or self.morph_overlord()
                or self.expand()
            ):
                self.planner.add_plan(plan)

        retreat_targets = frozenset([s.position for s in self.structures] + [self.start_location])
        attack_targets = frozenset([p.position for p in self.all_enemy_units] + self.enemy_start_locations)
        combat = Combat(prediction, retreat_targets, attack_targets)

        unit_acted: set[int] = set()
        async for action in self.micro(prediction, strategy, combat):
            if hasattr(action, "unit"):
                tag = cast(Unit, getattr(action, "unit")).tag
                if tag in unit_acted:
                    logger.info(f"Skipping duplicate action: {action}")
                else:
                    unit_acted.add(tag)
            success = await action.execute(self)
            if not success:
                await self.add_replay_tag("action_failed")
                logger.error(f"Action failed: {action}")

        if self.config[DEBUG]:
            self.profiler.disable()
            stats = pstats.Stats(self.profiler)
            if iteration % 100 == 0:
                logger.info("dump profiling")
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename="profiling.prof")

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

    async def micro(
        self,
        prediction: Prediction,
        strategy: Strategy,
        combat: Combat,
    ) -> AsyncGenerator[Action, None]:

        creep_context = self.creep.update(self)

        queens = self.actual_by_type[UnitTypeId.QUEEN]
        changelings = chain.from_iterable(self.actual_by_type[t] for t in CHANGELINGS)

        self.inject.assign(queens, self.townhalls.ready)

        should_inject = self.supply_used + self.larva.amount < 200
        should_spread_creep = self.creep.active_tumor_count < 10

        for action in self.state.actions_unit_commands:
            if action.exact_id == AbilityId.EFFECT_CORROSIVEBILE:
                for tag in action.unit_tags:
                    self._bile_last_used[tag] = self.state.game_loop

        scouts = self.units({UnitTypeId.OVERLORD, UnitTypeId.OVERSEER})
        blocked_positions = set(self._blocked_positions)
        scout_actions = {a.unit: a for a in self.scout.do_scouting(self, scouts, blocked_positions)}
        macro_actions = await self.planner.do_macro(self, blocked_positions)

        def should_harvest(u: Unit) -> bool:
            if u in macro_actions:  # got special orders?
                return False
            elif u.is_idle:  # you slackin?
                return True
            elif u.orders[0].ability.exact_id in ALL_MACRO_ABILITIES:
                return False  # alright, carry on!
            return True  # get on with it!

        required = self.cost.zero
        required += self.planner.get_total_cost(self.cost)
        required += self.cost.of_composition(strategy.composition_deficit)
        required -= self.bank
        mineral_trips = required.minerals / 5
        vespene_trips = required.vespene / 4
        gas_ratio = vespene_trips / max(1.0, mineral_trips + vespene_trips)

        def should_harvest_resource(r: Unit) -> bool:
            p = r.position.rounded
            return 0 <= combat.prediction.confidence[p] or 0 == combat.prediction.enemy_presence.dps[p]

        harvesters = self.workers.filter(should_harvest)
        resources_to_harvest = self.all_taken_resources.filter(should_harvest_resource)
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
            self.planner.add_plan(plan)

        dodge = self.dodge.update(self)

        def micro_queen(q: Unit) -> Action:
            return (
                dodge.dodge_with(q)
                or do_transfuse_single(q, prediction.context.units)
                or (self.inject.inject_with(q) if should_inject else None)
                or (creep_context.spread_creep_with_queen(q) if should_spread_creep else None)
                or combat.fight_with(self, q)
                or DoNothing()
            )

        for worker in harvesters:
            yield self.micro_harvester(worker, combat, dodge, resource_report)
        for action in macro_actions.values():
            yield action
        for tumor in self.creep.get_active_tumors(self):
            if action := creep_context.place_tumor(tumor):
                yield action
        for queen in queens:
            yield micro_queen(queen)

        for unit in changelings:
            if action := self.search_with(unit):
                yield action

        for unit in prediction.context.units:
            if unit in scout_actions:
                pass
            elif unit in macro_actions:
                pass
            elif action := dodge.dodge_with(unit):
                yield action
            elif unit.type_id in {UnitTypeId.OVERSEER} and (action := self.do_spawn_changeling(unit)):
                yield action
            elif unit.type_id in {UnitTypeId.ROACH} and (action := self.do_burrow(unit)):
                yield action
            elif unit.type_id in {UnitTypeId.ROACHBURROWED} and (action := self.do_unburrow(unit, combat)):
                yield action
            elif unit.type_id in {UnitTypeId.RAVAGER} and (action := self.do_bile(unit)):
                yield action
            elif unit.type_id in {UnitTypeId.QUEEN}:
                pass
            elif action := combat.fight_with(self, unit):
                yield action
            elif action := self.search_with(unit):
                yield action
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
        self, unit: Unit, combat_context: Combat, dodge: DodgeResult, resources: ResourceReport
    ) -> Action:
        return (
            dodge.dodge_with(unit)
            or resources.gather_with(unit, self.townhalls.ready)
            or combat_context.fight_with(self, unit)
            or DoNothing()
        )

    def run_build_order(self) -> bool:
        for i, step in enumerate(self.build_order.steps):
            if self.count(step.unit, include_planned=False) < step.count:
                if self.count(step.unit, include_planned=True) < step.count:
                    self.planner.add_plan(MacroPlan(step.unit, priority=-i))
                return False
        return True

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

    async def check_for_duplicate_actions(self, actions: list[Action]) -> None:
        actions_of_unit: defaultdict[Unit, list[Action]] = defaultdict(list)
        for action in actions:
            if hasattr(action, "unit"):
                unit = getattr(action, "unit")
                actions_of_unit[unit].append(action)
        for unit, unit_actions in actions_of_unit.items():
            if len(unit_actions) > 1:
                logger.error(f"Unit {unit} received multiple commands: {actions}")
                await self.add_replay_tag("conflicting_commands")
            for a in unit_actions[1:]:
                actions.remove(a)

    def detect_blocked_bases(self) -> None:
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

    def reset_blocked_bases(self) -> None:
        for position, blocked_since in list(self._blocked_positions.items()):
            if blocked_since + 60 < self.time:
                del self._blocked_positions[position]

    def make_composition(self, composition: UnitComposition) -> MacroPlan | None:
        if 200 <= self.supply_used:
            return None
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
                return MacroPlan(unit, priority=priority)
        return None

    def make_tech(self, strategy: Strategy) -> MacroPlan | None:
        upgrades = [
            u for unit in strategy.composition_target for u in self.upgrades_by_unit(unit) if strategy.filter_upgrade(u)
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
                return MacroPlan(target, priority=-0.5)
        return None

    def morph_overlord(self) -> MacroPlan | None:
        supply = self.supply_cap + self.supply_pending / 2 + self.supply_planned
        supply_target = min(200.0, self.supply_used + 2 + 20 * self.income.larva)
        if supply_target < supply:
            return None
        return MacroPlan(UnitTypeId.OVERLORD, priority=1)

    def expand(self) -> MacroPlan | None:

        if self.time < 50:
            return None
        if 2 == self.townhalls.amount and 2 > self.count(UnitTypeId.QUEEN, include_planned=False):
            return None

        worker_max = self._max_harvesters
        saturation = max(0, min(1, self.state.score.food_used_economy / max(1, worker_max)))
        if 2 < self.townhalls.amount and 2 / 3 > saturation:
            return None

        priority = 3 * (saturation - 1)
        for plan in self.planned_by_type(UnitTypeId.HATCHERY):
            if plan.priority < math.inf:
                plan.priority = priority

        if 0 < self.count(UnitTypeId.HATCHERY, include_actual=False):
            return None
        return MacroPlan(UnitTypeId.HATCHERY, priority=priority, max_distance=None)

    def do_bile(self, unit: Unit) -> Action | None:

        ability = AbilityId.EFFECT_CORROSIVEBILE

        def bile_priority(t: Unit) -> float:
            if not t.is_enemy:
                return 0.0
            if not self.is_visible(t.position):
                return 0.0
            if not unit.in_ability_cast_range(ability, t.position):
                return 0.0
            if t.is_hallucination:
                return 0.0
            if t.type_id in CHANGELINGS:
                return 0.0
            priority = 10.0 + max(t.ground_dps, t.air_dps)
            priority /= 100.0 + t.health + t.shield
            priority /= 2.0 + t.movement_speed
            return priority

        if unit.type_id != UnitTypeId.RAVAGER:
            return None

        last_used = self._bile_last_used.get(unit.tag, 0)

        if self.state.game_loop < last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        target = max(
            self.all_enemy_units,
            key=lambda t: bile_priority(t),
            default=None,
        )

        if not target:
            return None

        if bile_priority(target) <= 0:
            return None

        return UseAbility(unit, ability, target=target.position)

    def do_burrow(self, unit: Unit) -> Action | None:

        if (
            UpgradeId.BURROW in self.state.upgrades
            and unit.health_percentage < 1 / 3
            and unit.weapon_cooldown
            and not unit.is_revealed
        ):
            return UseAbility(unit, AbilityId.BURROWDOWN)

        return None

    def do_spawn_changeling(self, unit: Unit) -> Action | None:
        if unit.type_id in {UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE}:
            if self.in_pathing_grid(unit):
                ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
                if ENERGY_COST[ability] <= unit.energy:
                    return UseAbility(unit, ability)
        return None

    def do_unburrow(self, unit: Unit, combat: Combat) -> Action | None:
        p = tuple[int, int](unit.position.rounded)
        confidence = combat.prediction.confidence[p]
        if unit.health_percentage == 1 and 0 < confidence:
            return UseAbility(unit, AbilityId.BURROWUP)
        elif UpgradeId.TUNNELINGCLAWS not in self.state.upgrades:
            return None
        elif 0 < combat.prediction.enemy_presence.dps[p]:
            retreat_path = combat.retreat_ground.get_path(p, 2)
            if combat.retreat_ground.dist[p] == np.inf:
                retreat_point = self.start_location
            else:
                retreat_point = Point2(retreat_path[-1]).offset(HALF)
            return Move(unit, retreat_point)
        return HoldPosition(unit)
