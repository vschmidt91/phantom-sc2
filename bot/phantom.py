import cProfile
import math
import pstats
from collections import defaultdict
from functools import cmp_to_key

from ares import AresBot
from loguru import logger
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit

from .action import Action
from .components.build_order import BuildOrder
from .components.chat import Chat
from .components.combat import Combat
from .components.creep import CreepSpread
from .components.dodge import Dodge
from .components.inject import Inject
from .components.macro import Macro, compare_plans
from .components.scout import Scout
from .components.strategy import Strategy
from .components.transfuse import Transfuse
from .cost import CostManager
from .resources.resource_manager import ResourceManager


class PhantomBot(
    BuildOrder,
    Combat,
    CreepSpread,
    Dodge,
    Inject,
    Macro,
    ResourceManager,
    Scout,
    Strategy,
    Transfuse,
    AresBot,
):

    debug = False
    profiler: cProfile.Profile | None = None
    chat = Chat()
    cost: CostManager

    def __init__(self, game_step_override: int | None = None) -> None:
        super().__init__(game_step_override=game_step_override)

    async def on_before_start(self):
        await super().on_before_start()
        self.cost = CostManager(self.calculate_cost, self.calculate_supply_cost)
        if self.debug:
            self.profiler = cProfile.Profile()

    async def on_start(self) -> None:
        await super().on_start()
        self.initialize_scout_targets(self.bases)
        self.split_initial_workers(self.workers)

    async def on_step(self, iteration: int):
        await super().on_step(iteration)

        if self.profiler:
            self.profiler.enable()

        if self.actual_iteration == 10:
            self.chat.add_message("(glhf)")

        self.assign_queens(self.actual_by_type[UnitTypeId.QUEEN], self.townhalls)
        if self.run_build_order():
            self.make_composition()
            self.make_tech()
            self.morph_overlords()
            self.expand()
            self.update_composition()

        actions: list[Action] = []
        actions.extend(self.chat.do_chat())
        actions.extend(self.do_macro())
        actions.extend(self.do_harvest())
        actions.extend(self.spread_creep())
        actions.extend(self.do_transfuse())
        actions.extend(self.do_injects())
        actions.extend(self.do_scouting())
        actions.extend(self.do_dodge())
        actions.extend(self.do_combat())

        if self.debug:
            self.check_for_duplicate_actions(actions)

        for action in actions:
            success = await action.execute(self)
            if not success:
                logger.error(f"Action failed: {action}")

        if self.profiler:
            self.profiler.disable()
            stats = pstats.Stats(self.profiler)
            if iteration % 100 == 0:
                logger.info("dump profiling")
                stats = stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE)
                stats.dump_stats(filename="profiling.prof")

        if self.debug:
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
        if unit.type_id in {UnitTypeId.DRONE, UnitTypeId.SCV, UnitTypeId.PROBE}:
            self.add_harvester(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        await super().on_unit_type_changed(unit, previous_type)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        await super().on_unit_took_damage(unit, amount_damage_taken)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        await super().on_upgrade_complete(upgrade)

    def check_for_duplicate_actions(self, actions: list[Action]) -> None:
        actions_of_unit: defaultdict[Unit, list[Action]] = defaultdict(list)
        for action in actions:
            if hasattr(action, "unit"):
                unit = getattr(action, "unit")
                actions_of_unit[unit].append(action)
        for unit, unit_actions in actions_of_unit.items():
            if len(unit_actions) > 1:
                logger.debug(f"Unit {unit} received multiple commands: {actions}")
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

        self.client.debug_text_screen(f"Confidence: {round(100 * self.confidence)}%", (0.01, 0.01))
        self.client.debug_text_screen(f"Gas Target: {round(self.get_gas_target(), 3)}", (0.01, 0.03))

        for i, plan in enumerate(plans):
            self.client.debug_text_screen(f"{1 + i} {round(plan.eta or 0, 1)} {plan.item.name}", (0.01, 0.1 + 0.01 * i))

    def morph_overlords(self) -> None:
        supply = self.supply_cap + self.supply_pending + self.supply_planned
        supply_target = min(200.0, self.supply_used + 4.0 + self.income.larva / 2.0)
        if supply < supply_target:
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
            expand = 21 <= self.state.score.food_used_economy
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
