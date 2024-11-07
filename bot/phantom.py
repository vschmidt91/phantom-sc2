import cProfile
import lzma
import math
import os
import pickle
import pstats
import random
from collections import defaultdict
from functools import cmp_to_key
from itertools import chain
from typing import AsyncGenerator, cast

import numpy as np
from ares import DEBUG, AresBot
from loguru import logger
from sc2.data import Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit

from .action import Action, AttackMove, DoNothing, UseAbility
from .build_order import HATCH_FIRST
from .chat import Chat, ChatMessage
from .combat import Combat
from .components.macro import Macro, compare_plans
from .components.scout import Scout
from .constants import (
    ALL_MACRO_ABILITIES,
    CHANGELINGS,
    CIVILIANS,
    COOLDOWN,
    ENERGY_COST, VERSION_FILE, UNKNOWN_VERSION,
)
from .creep import CreepSpread
from .dodge import Dodge, DodgeResult
from .inject import Inject
from .predictor import Prediction, PredictorContext, predict
from .resources.resource_manager import ResourceManager
from .strategy import decide_strategy
from .transfuse import do_transfuse_single


class PhantomBot(
    Macro,
    ResourceManager,
    Scout,
    AresBot,
):
    creep = CreepSpread()
    chat = Chat()
    inject = Inject()
    dodge = Dodge()
    build_order = HATCH_FIRST
    profiler = cProfile.Profile()
    version = UNKNOWN_VERSION

    _bile_last_used = dict[int, int]()

    async def on_before_start(self):
        await super().on_before_start()

    async def on_start(self) -> None:
        await super().on_start()
        # if self.config[DEBUG]:
        #     output_path = os.path.join("resources", f"{self.game_info.map_name}.xz")
        #     with lzma.open(output_path, "wb") as f:
        #         pickle.dump(self.game_info, f)
        #     await self.client.debug_create_unit([[UnitTypeId.PYLON, 1, self.bases[1].position, 2]])
        #     await self.client.debug_create_unit(
        #         [
        #             [UnitTypeId.PYLON, 1, self.bases[1].position, 2],
        #             [UnitTypeId.RAVAGER, 10, self.bases[1].position, 1],
        #             [UnitTypeId.RAVAGER, 10, self.bases[2].position, 2],
        #             [UnitTypeId.BANELING, 10, self.bases[1].position, 1],
        #             [UnitTypeId.BANELING, 10, self.bases[2].position, 2],
        #         ]
        #     )
        self.initialize_resources()
        self.initialize_scout_targets(self.bases)
        self.split_initial_workers(self.workers)

        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE) as f:
                version = f.read()
                self.add_replay_tag(f"{version=}")

    async def send_chat_message(self, message: ChatMessage) -> None:
        await self.client.chat_send(message.message, message.team_only)

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        if self.config[DEBUG]:
            # local only: skip first iteration like on the ladder
            if iteration == 0:
                return
            self.profiler.enable()

        await self.chat.do_chat(self.send_chat_message)
        dodge = self.dodge.update(self)

        army = self.units.exclude_type(CIVILIANS)
        enemies = self.all_enemy_units
        predictor_context = PredictorContext(
            units=army,
            enemy_units=enemies,
            dps=self.dps_fast,
            pathing=self.mediator.get_map_data_object.get_pyastar_grid(),
            air_pathing=self.mediator.get_map_data_object.get_clean_air_grid(),
        )
        prediction = predict(predictor_context)
        worker_target = max(1, min(80, self.max_harvesters))
        strategy = decide_strategy(self, worker_target, prediction.confidence_global)

        if self.run_build_order():
            self.make_composition(strategy.composition)
            self.make_tech(strategy)
            self.morph_overlords()
            self.expand()

        retreat_targets = [w.position for w in self.workers] + [self.start_location]
        combat = Combat(prediction, retreat_targets)

        unit_acted: set[int] = set()
        async for action in self.micro(strategy.composition, prediction, dodge, combat):
            if hasattr(action, "unit"):
                tag = cast(Unit, getattr(action, "unit")).tag
                if tag in unit_acted:
                    logger.info(f"Skipping duplicate action: {action}")
                else:
                    unit_acted.add(tag)
            success = await action.execute(self)
            if not success:
                logger.error(f"Action failed: {action}")

        if self.config[DEBUG]:
            self.profiler.disable()
            stats = pstats.Stats(self.profiler)
            if iteration % 100 == 0:
                logger.info("dump profiling")
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename="profiling.prof")
            await self.draw_debug()

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

    def add_replay_tag(self, tag: str) -> None:
        self.chat.add_message(f"Tag:{tag}", True)

    async def micro(
        self, composition: dict[UnitTypeId, int], prediction: Prediction, dodge: DodgeResult, combat: Combat
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

        def micro_queen(q: Unit) -> Action:
            return (
                dodge.dodge_with(q)
                or do_transfuse_single(q, prediction.context.units)
                or (self.inject.inject_with(q) if should_inject else None)
                or (creep_context.spread_creep_with_queen(q) if should_spread_creep else None)
                or combat.fight_with(self, q)
                or DoNothing()
            )

        scouts = self.units({UnitTypeId.OVERLORD, UnitTypeId.OVERSEER})
        scout_actions = {a.unit: a for a in self.do_scouting(scouts)}

        macro_actions = {ma.unit: ma.action async for ma in self.do_macro()}

        harvesters: list[Unit] = []
        for worker in self.workers:
            if not worker.is_idle and worker.orders[0].ability.exact_id in ALL_MACRO_ABILITIES:
                pass
            elif worker in macro_actions:
                pass
            else:
                harvesters.append(worker)
        self.assign_harvesters(harvesters, self.get_future_spending(composition))

        for worker in harvesters:
            yield self.micro_harvester(worker, combat, dodge)
        for action in macro_actions.values():
            yield action
        for tumor in self.creep.get_active_tumors(self):
            if action := creep_context.place_tumor(tumor):
                yield action
        for queen in queens:
            yield micro_queen(queen)

        for unit in changelings:
            if action := self.do_scout(unit):
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
            elif unit.type_id in {UnitTypeId.ROACHBURROWED} and (action := self.do_unburrow(unit)):
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

    def micro_harvester(self, unit: Unit, combat_context: Combat, dodge: DodgeResult) -> Action:
        return (
            dodge.dodge_with(unit)
            or self.gather_with(unit, self.townhalls.ready)
            or combat_context.fight_with(self, unit)
            or DoNothing()
        )

    def run_build_order(self) -> bool:
        for i, step in enumerate(self.build_order.steps):
            if self.count(step.unit, include_planned=False) < step.count:
                if self.count(step.unit, include_planned=True) < step.count:
                    plan = self.add_plan(step.unit)
                    plan.priority = -i
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

    def check_for_duplicate_actions(self, actions: list[Action]) -> None:
        actions_of_unit: defaultdict[Unit, list[Action]] = defaultdict(list)
        for action in actions:
            if hasattr(action, "unit"):
                unit = getattr(action, "unit")
                actions_of_unit[unit].append(action)
        for unit, unit_actions in actions_of_unit.items():
            if len(unit_actions) > 1:
                logger.error(f"Unit {unit} received multiple commands: {actions}")
                self.add_replay_tag("Conflicting commands")
            for a in unit_actions[1:]:
                actions.remove(a)

    async def draw_debug(self):
        font_color = (255, 255, 255)
        font_size = 12

        plans = sorted(
            self.enumerate_plans(),
            key=cmp_to_key(compare_plans),
            reverse=True,
        )

        for i, target in enumerate(plans):
            positions = []

            if not target.target:
                pass
            elif isinstance(target.target, Unit):
                positions.append(target.target.position3d)
            elif isinstance(target.target, Point3):
                positions.append(target.target)
            elif isinstance(target.target, Point2):
                height = self.get_terrain_z_height(target.target)
                positions.append(Point3((target.target.x, target.target.y, height)))

            text = f"{str(i + 1)} {target.item.name}"

            for position in positions:
                self.client.debug_text_world(text, position, color=font_color, size=font_size)

            if len(positions) == 2:
                position_from, position_to = positions
                position_from += Point3((0.0, 0.0, 0.1))
                position_to += Point3((0.0, 0.0, 0.1))
                self.client.debug_line_out(position_from, position_to, color=font_color)

        font_color = (255, 0, 0)

        for enemy in self.all_enemy_units:
            pos = enemy.position
            position = Point3((*pos, self.get_terrain_z_height(pos)))
            text = f"{enemy.name}"
            self.client.debug_text_world(text, position, color=font_color, size=font_size)

        # self.client.debug_text_screen(f"Confidence: {round(100 * self.confidence)}%", (0.01, 0.01))
        # self.client.debug_text_screen(f"Gas Target: {round(self.get_gas_target(), 3)}", (0.01, 0.03))

        for i, plan in enumerate(plans):
            self.client.debug_text_screen(f"{1 + i} {round(plan.eta or 0, 1)} {plan.item.name}", (0.01, 0.1 + 0.01 * i))

    def morph_overlords(self) -> None:
        supply = self.supply_cap + self.supply_pending + self.supply_planned
        supply_target = min(200.0, self.supply_used + 4.0 + self.income.larva / 2.0)
        if supply <= supply_target:
            plan = self.add_plan(UnitTypeId.OVERLORD)
            plan.priority = 1

    def expand(self) -> None:

        if self.time < 50:
            return

        worker_max = self.max_harvesters
        saturation = self.state.score.food_used_economy / max(1, worker_max)
        saturation = max(0, min(1, saturation))
        priority = 3 * (saturation - 1)

        expand = True
        if self.townhalls.amount == 2:
            expand = 2 <= self.count(UnitTypeId.QUEEN, include_planned=False)
            # expand = 25 <= self.state.score.food_used_economy
        elif 2 < self.townhalls.amount:
            expand = 2 / 3 < saturation

        for plan in self.planned_by_type(UnitTypeId.HATCHERY):
            if plan.priority < math.inf:
                plan.priority = priority

        if expand and self.count(UnitTypeId.HATCHERY, include_actual=False) < 1:
            plan = self.add_plan(UnitTypeId.HATCHERY)
            plan.priority = priority
            plan.max_distance = None
            logger.info(f"Expanding: {plan=}")

    def do_bile(self, unit: Unit) -> Action | None:

        ability = AbilityId.EFFECT_CORROSIVEBILE

        def bile_priority(target: Unit) -> float:
            if not target.is_enemy:
                return 0.0
            if not self.is_visible(target.position):
                return 0.0
            if not unit.in_ability_cast_range(ability, target.position):
                return 0.0
            if target.is_hallucination:
                return 0.0
            if target.type_id in CHANGELINGS:
                return 0.0
            priority = 10.0 + max(target.ground_dps, target.air_dps)
            priority /= 100.0 + target.health + target.shield
            priority /= 2.0 + target.movement_speed
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

    def do_scout(self, unit: Unit) -> Action | None:
        if unit.is_idle:
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

    def do_spawn_changeling(self, unit: Unit) -> Action | None:
        if unit.type_id in {UnitTypeId.OVERSEER, UnitTypeId.OVERSEERSIEGEMODE}:
            if self.in_pathing_grid(unit):
                ability = AbilityId.SPAWNCHANGELING_SPAWNCHANGELING
                if ENERGY_COST[ability] <= unit.energy:
                    return UseAbility(unit, ability)
        return None

    def do_unburrow(self, unit: Unit) -> Action | None:
        if unit.health_percentage == 1 or unit.is_revealed:
            return UseAbility(unit, AbilityId.BURROWUP)
        return None
