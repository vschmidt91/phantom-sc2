import math
import random
from dataclasses import dataclass
from itertools import chain
from typing import Iterable, TypeAlias

from loguru import logger
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.action import CombatAction
from bot.common.action import Action, HoldPosition, Move, UseAbility
from bot.common.constants import (
    ALL_MACRO_ABILITIES,
    GAS_BY_RACE,
    ITEM_BY_ABILITY,
    ITEM_TRAINED_FROM_WITH_EQUIVALENTS,
    MACRO_INFO,
)
from bot.common.cost import Cost, CostManager
from bot.common.main import BotBase
from bot.common.utils import PlacementNotFoundException
from bot.observation import Observation

MacroId: TypeAlias = UnitTypeId | UpgradeId


@dataclass
class MacroPlan:
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0
    max_distance: int | None = 4
    executed: bool = False
    commanded: bool = False


class MacroState:
    unassigned_plans = list[MacroPlan]()
    assigned_plans = dict[int, MacroPlan]()

    @property
    def plan_count(self) -> int:
        return len(self.unassigned_plans) + len(self.assigned_plans)

    def add(self, plan: MacroPlan) -> None:
        self.unassigned_plans.append(plan)
        logger.info(f"Adding {plan=}")

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self.assigned_plans.values(), self.unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return (plan for plan in self.enumerate_plans() if plan.item == item)

    def assign_unassigned_plans(self, trainers: Units) -> None:
        trainer_set = set(trainers)
        for plan in list(self.unassigned_plans):
            if trainer := self.find_trainer(trainer_set, plan.item):
                logger.info(f"Assigning {trainer=} for {plan=}")
                if plan in self.unassigned_plans:
                    self.unassigned_plans.remove(plan)
                self.assigned_plans[trainer.tag] = plan
                trainer_set.remove(trainer)

    async def get_actions(
        self, obs: Observation, blocked_positions: set[Point2], combat: CombatAction
    ) -> dict[Unit, Action]:

        self._handle_actions(obs.bot)
        self.assign_unassigned_plans(obs.bot.all_own_units)  # TODO: narrow this down

        actions = dict[Unit, Action]()
        reserve = obs.bot.cost.zero
        plans_prioritized = sorted(self.assigned_plans.items(), key=lambda p: p[1].priority, reverse=True)
        for i, (tag, plan) in enumerate(plans_prioritized):

            if plan.commanded and plan.executed:
                del self.assigned_plans[tag]
                logger.info(f"Successfully executed {plan=}")
                continue

            trainer = obs.bot.unit_tag_dict.get(tag)
            if not trainer:
                del self.assigned_plans[tag]
                self.unassigned_plans.append(plan)
                logger.info(f"{trainer} is MIA for {plan}")
                continue

            if trainer.type_id == UnitTypeId.EGG:
                del self.assigned_plans[tag]
                self.unassigned_plans.append(plan)
                logger.info(f"{trainer} is an egg")
                continue

            ability = MACRO_INFO.get(trainer.type_id, {}).get(plan.item, {}).get("ability")
            if not ability:
                del self.assigned_plans[tag]
                self.unassigned_plans.append(plan)
                logger.info(f"{trainer=} is unable to execute {plan=}")
                continue

            if any(obs.get_missing_requirements(plan.item)):
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
                if not await obs.bot.can_place_single(plan.item, plan.target):
                    plan.target = None
                    plan.commanded = False
                    plan.executed = False

            if not plan.target:
                try:
                    plan.target = await self.get_target(obs, trainer, plan, blocked_positions)
                except PlacementNotFoundException:
                    continue

            cost = obs.bot.cost.of(plan.item)
            eta = get_eta(obs, reserve, cost)

            if eta < math.inf:
                expected_income = obs.income * eta
                needs_to_reserve = Cost.max(obs.bot.cost.zero, cost - expected_income)
                reserve += needs_to_reserve

            if eta == 0.0:
                plan.commanded = True
                actions[trainer] = UseAbility(trainer, ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(trainer, AbilityId.HARVEST_RETURN)
                elif action := await premove(obs.bot, trainer, plan.target.position, eta):
                    actions[trainer] = action
                elif action := combat.fight_with(trainer):
                    actions[trainer] = action

        return actions

    def get_total_cost(self, cost: CostManager) -> Cost:
        costs = []
        costs.extend([cost.of(plan.item) for plan in self.unassigned_plans])
        costs.extend(cost.of(plan.item) for plan in self.assigned_plans.values())
        return sum(costs, cost.zero)

    async def get_target(
        self, obs: Observation, trainer: Unit, objective: MacroPlan, blocked_positions: set[Point2]
    ) -> Unit | Point2 | None:
        gas_type = GAS_BY_RACE[obs.bot.race]
        if objective.item == gas_type:
            exclude_positions = {geyser.position for geyser in obs.bot.gas_buildings}
            exclude_tags = {
                order.target
                for unit in obs.bot.workers
                for order in unit.orders
                if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
            }
            exclude_tags.update({p.target.tag for p in self.planned_by_type(gas_type) if isinstance(p.target, Unit)})
            owned_geysers = [g for b in obs.bases_taken for g in obs.bot.expansion_locations_dict[b].vespene_geyser]
            geysers = [
                geyser
                for geyser in owned_geysers
                if (geyser.position not in exclude_positions and geyser and geyser.tag not in exclude_tags)
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
            position = await get_target_position(obs, objective.item, blocked_positions)
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
                and trainer.tag not in self.assigned_plans
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
            for t, p in self.assigned_plans.items():
                if item == p.item and not p.executed:
                    tag = t
                    break
        if plan := self.assigned_plans.get(tag):
            if item == plan.item:
                plan.executed = True
                logger.info(f"Executed {plan} through {action}")
        elif action.exact_id in ALL_MACRO_ABILITIES:
            logger.info(f"Unplanned {action}")


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


def get_eta(observation: Observation, reserve: Cost, cost: Cost) -> float:
    deficit = reserve + cost - observation.bank
    eta = deficit / observation.income
    return max(
        (
            0.0,
            eta.minerals if 0 < deficit.minerals and 0 < cost.minerals else 0.0,
            eta.vespene if 0 < deficit.vespene and 0 < cost.vespene else 0.0,
            eta.larva if 0 < deficit.larva and 0 < cost.larva else 0.0,
            eta.supply if 0 < deficit.supply and 0 < cost.supply else 0.0,
        )
    )


async def get_target_position(obs: Observation, target: UnitTypeId, blocked_positions: set[Point2]) -> Point2 | None:
    data = obs.bot.game_data.units[target.value]
    if target in {UnitTypeId.HATCHERY}:
        candidates = [
            b for b in obs.bot.expansion_locations_list if b not in blocked_positions and b not in obs.townhall_at
        ]
        if not candidates:
            return None
        loss_positions = {obs.in_mineral_line(b) for b in obs.bases_taken} | {obs.bot.start_location}
        loss_positions_enemy = {obs.in_mineral_line(s) for s in obs.bot.enemy_start_locations}

        async def loss_fn(p: Point2) -> float:
            distances = await obs.bot.client.query_pathings([[p, q] for q in loss_positions])
            distances_enemy = await obs.bot.client.query_pathings([[p, q] for q in loss_positions_enemy])
            return max(distances) - min(distances_enemy)

        c_min = candidates[0]
        loss_min = await loss_fn(c_min)
        for c in candidates[1:]:
            loss = await loss_fn(c)
            if loss < loss_min:
                loss_min = loss
                c_min = c
        return c_min

    bases = list(obs.bot.expansion_locations_dict.items())
    random.shuffle(bases)
    for pos, resources in bases:
        if not (base := obs.townhall_at.get(pos)):
            continue
        if not base.is_ready:
            continue
        position = pos.towards_with_random_angle(obs.behind_mineral_line(pos), 10)
        offset = data.footprint_radius % 1
        position = position.rounded.offset((offset, offset))
        return position
    return None
