import math
import random
from dataclasses import dataclass
from itertools import chain
from typing import Callable, Iterable, TypeAlias

from ares import DEBUG
from loguru import logger
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units

from bot.action import Action, HoldPosition, Move, UseAbility
from bot.base import BotBase
from bot.constants import (
    ALL_MACRO_ABILITIES,
    GAS_BY_RACE,
    ITEM_BY_ABILITY,
    ITEM_TRAINED_FROM_WITH_EQUIVALENTS,
    MACRO_INFO,
)
from bot.cost import Cost
from bot.utils import PlacementNotFoundException

MacroId: TypeAlias = UnitTypeId | UpgradeId


@dataclass
class MacroPlan:
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0
    max_distance: int | None = 4
    executed: bool = False
    commanded: bool = False


MacroPriority: TypeAlias = Callable[[MacroPlan], float]


def compare_plans(plan_a: MacroPlan, plan_b: MacroPlan) -> int:
    if plan_a.priority < plan_b.priority:
        return -1
    elif plan_b.priority < plan_a.priority:
        return +1
    return 0


async def premove(context: BotBase, unit: Unit, target: Point2, eta: float) -> Action | None:
    distance = await context.client.query_pathing(unit, target) or 0.0
    movement_eta = 1.5 + distance / (1.4 * unit.movement_speed)
    if eta <= movement_eta:
        if 1e-3 < unit.distance_to(target):
            return Move(unit, target)
        else:
            return HoldPosition(unit)
    return None


def get_eta(context: BotBase, reserve: Cost, cost: Cost) -> float:
    deficit = reserve + cost - context.bank
    eta = deficit / context.income
    return max(
        (
            0.0,
            eta.minerals if 0 < deficit.minerals and 0 < cost.minerals else 0.0,
            eta.vespene if 0 < deficit.vespene and 0 < cost.vespene else 0.0,
            eta.larva if 0 < deficit.larva and 0 < cost.larva else 0.0,
            eta.supply if 0 < deficit.supply and 0 < cost.supply else 0.0,
        )
    )


def get_target_position(context: BotBase, target: UnitTypeId, blocked_positions: set[Point2]) -> Point2 | None:
    data = context.game_data.units[target.value]
    if target in {UnitTypeId.HATCHERY}:
        for base in context.bases:
            if base.townhall:
                continue
            if base.position.rounded in blocked_positions:
                continue
            if base.mineral_patches.remaining < 500 and base.vespene_geysers.remaining == 0:
                continue
            return base.position
        return None

    bases = list(context.bases)
    random.shuffle(bases)
    for base in bases:
        if not base.townhall:
            continue
        elif not base.townhall.is_ready:
            continue
        position = base.position.towards_with_random_angle(base.mineral_patches.position, 10)
        offset = data.footprint_radius % 1
        position = position.rounded.offset((offset, offset))
        return position
    return None


def _debug_draw_plan(
    context: BotBase,
    unit: Unit | None,
    plan: MacroPlan,
    eta: float,
    index: int,
    font_color=(255, 255, 255),
    font_size=16,
) -> None:
    positions = []
    if isinstance(plan.target, Unit):
        positions.append(plan.target.position3d)
    elif isinstance(plan.target, Point3):
        positions.append(plan.target)
    elif isinstance(plan.target, Point2):
        height = context.get_terrain_z_height(plan.target)
        positions.append(Point3((plan.target.x, plan.target.y, height)))

    if unit:
        height = context.get_terrain_z_height(unit)
        positions.append(Point3((unit.position.x, unit.position.y, height)))

    text = f"{plan.item.name} {eta:.2f}"

    for position in positions:
        context.client.debug_text_world(text, position, color=font_color, size=font_size)

    if len(positions) == 2:
        position_from, position_to = positions
        position_from += Point3((0.0, 0.0, 0.1))
        position_to += Point3((0.0, 0.0, 0.1))
        context.client.debug_line_out(position_from, position_to, color=font_color)

    context.client.debug_text_screen(f"{1 + index} {round(eta or 0, 1)} {plan.item.name}", (0.01, 0.1 + 0.01 * index))


class Macro:
    _unassigned_plans: list[MacroPlan] = list()
    _assigned_plans: dict[int, MacroPlan] = dict()

    def add_plan(self, plan: MacroPlan) -> None:
        self._unassigned_plans.append(plan)
        logger.info(f"Adding {plan=}")

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self._assigned_plans.values(), self._unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return (plan for plan in self.enumerate_plans() if plan.item == item)

    def assign_unassigned_plans(self, trainers: Units) -> None:
        trainer_set = set(trainers)
        for plan in list(self._unassigned_plans):
            if trainer := self.find_trainer(trainer_set, plan.item):
                logger.info(f"Assigning {trainer=} for {plan=}")
                if plan in self._unassigned_plans:
                    self._unassigned_plans.remove(plan)
                self._assigned_plans[trainer.tag] = plan
                trainer_set.remove(trainer)

    async def do_macro(self, context: BotBase, blocked_positions: set[Point2]) -> dict[Unit, Action]:

        self._handle_actions(context)
        self.assign_unassigned_plans(context.all_own_units)  # TODO: narrow this down

        actions = dict[Unit, Action]()
        reserve = Cost(0, 0, 0, 0)
        plans_prioritized = sorted(self._assigned_plans.items(), key=lambda p: p[1].priority, reverse=True)
        for i, (tag, plan) in enumerate(plans_prioritized):

            if plan.commanded and plan.executed:
                del self._assigned_plans[tag]
                logger.info(f"Successfully executed {plan=}")
                continue

            trainer = context.unit_tag_dict.get(tag)
            if not trainer:
                del self._assigned_plans[tag]
                self._unassigned_plans.append(plan)
                logger.info(f"{trainer} is MIA for {plan}")
                continue

            if trainer.type_id == UnitTypeId.EGG:
                del self._assigned_plans[tag]
                self._unassigned_plans.append(plan)
                logger.info(f"{trainer} is an egg")
                continue

            ability = MACRO_INFO.get(trainer.type_id, {}).get(plan.item, {}).get("ability")
            if not ability:
                del self._assigned_plans[tag]
                self._unassigned_plans.append(plan)
                logger.info(f"{trainer=} is unable to execute {plan=}")
                continue

            if any(context.get_missing_requirements(plan.item)):
                continue

            # reset target on failure
            if plan.executed:
                logger.info(f"resetting target for {plan=}")
                # if isinstance(plan.target, Point2):
                #     if plan.target not in self.blocked_positions:
                #         self.blocked_positions[plan.target] = self.time
                #         logger.info(f"Blocked location detected by {plan}")
                plan.target = None
                plan.commanded = False
                plan.executed = False

            if isinstance(plan.target, Point2):
                if not await context.can_place_single(plan.item, plan.target):
                    plan.target = None
                    plan.commanded = False
                    plan.executed = False

            if not plan.target:
                try:
                    plan.target = self.get_target(context, trainer, plan, blocked_positions)
                except PlacementNotFoundException:
                    continue

            cost = context.cost.of(plan.item)
            eta = get_eta(context, reserve, cost)
            if eta < math.inf:
                reserve += cost

            if eta == 0.0:
                plan.commanded = True
                actions[trainer] = UseAbility(trainer, ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(trainer, AbilityId.HARVEST_RETURN)
                elif action := await premove(context, trainer, plan.target.position, eta):
                    actions[trainer] = action

            if context.config[DEBUG]:
                _debug_draw_plan(context, trainer, plan, eta, i)

        return actions

    def get_future_spending(self, context: BotBase, composition: dict[UnitTypeId, int]) -> Cost:
        cost_zero = Cost(0, 0, 0, 0)
        future_spending = cost_zero
        future_spending += sum((context.cost.of(plan.item) for plan in self._unassigned_plans), cost_zero)
        future_spending += sum(
            (context.cost.of(plan.item) for plan in self._assigned_plans.values()),
            cost_zero,
        )
        future_spending += sum(
            (context.cost.of(unit) * max(0, count - context.count(unit)) for unit, count in composition.items()),
            cost_zero,
        )
        return future_spending

    def get_target(
        self, context: BotBase, trainer: Unit, objective: MacroPlan, blocked_positions: set[Point2]
    ) -> Unit | Point2 | None:
        gas_type = GAS_BY_RACE[context.race]
        if objective.item == gas_type:
            exclude_positions = {geyser.position for geyser in context.gas_buildings}
            exclude_tags = {
                order.target
                for unit in context.workers
                for order in unit.orders
                if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
            }
            exclude_tags.update({p.target.tag for p in self.planned_by_type(gas_type) if isinstance(p.target, Unit)})
            geysers = [
                geyser.unit
                for geyser in context.owned_geysers
                if (geyser.position not in exclude_positions and geyser.unit and geyser.unit.tag not in exclude_tags)
            ]
            if not any(geysers):
                raise PlacementNotFoundException()
            else:
                return min(geysers, key=lambda g: g.tag)

        if not (entry := MACRO_INFO.get(trainer.type_id)):
            return None
        if not (data := entry.get(objective.item)):
            return None
        # data = MACRO_INFO[trainer.unit.type_id][objective.item]

        if "requires_placement_position" in data:
            position = get_target_position(context, objective.item, blocked_positions)
            if not position:
                raise PlacementNotFoundException()
            return position
        else:
            return None

    def find_trainer(self, trainers: Iterable[Unit], item: MacroId) -> Unit | None:
        trainer_types = ITEM_TRAINED_FROM_WITH_EQUIVALENTS[item]

        trainers_filtered = [
            trainer
            for trainer in trainers
            if (
                trainer.type_id in trainer_types
                and trainer.is_ready
                and (trainer.is_idle or not trainer.is_structure)
                and trainer.tag not in self._assigned_plans
            )
        ]

        if any(trainers_filtered):
            # trainers_filtered.sort(key=lambda t: t.tag)
            return trainers_filtered[0]

        return None

    def _handle_actions(self, context: BotBase) -> None:
        for action in context.state.actions_unit_commands:
            for tag in action.unit_tags:
                self._handle_action(context, action, tag)

    def _handle_action(self, context: BotBase, action: ActionRawUnitCommand, tag: int) -> None:
        unit = context.unit_tag_dict.get(tag)

        if not (item := ITEM_BY_ABILITY.get(action.exact_id)):
            return
        elif item in {UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.CREEPTUMOR, UnitTypeId.CHANGELING}:
            return
        if unit and unit.type_id == UnitTypeId.EGG:
            # commands issued to a specific larva will be received by a random one
            # therefore, a direct lookup will often be incorrect
            # instead, all plans are checked for a match
            for t, p in self._assigned_plans.items():
                if item == p.item and not p.executed:
                    tag = t
                    break
        if plan := self._assigned_plans.get(tag):
            if item == plan.item:
                plan.executed = True
                logger.info(f"Executed {plan} through {action}")
        elif action.exact_id in ALL_MACRO_ABILITIES:
            logger.info(f"Unplanned {action}")