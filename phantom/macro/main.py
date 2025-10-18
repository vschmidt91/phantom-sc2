import math
import random
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from itertools import chain

import numpy as np
from ares.consts import UnitRole
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from phantom.common.action import Action, HoldPosition, Move, UseAbility
from phantom.common.constants import (
    GAS_BY_RACE,
    HALF,
    ITEM_TRAINED_FROM_WITH_EQUIVALENTS,
    MACRO_INFO,
    WORKERS,
)
from phantom.common.cost import Cost
from phantom.common.unit_composition import UnitComposition
from phantom.common.utils import PlacementNotFoundException, Point
from phantom.knowledge import Knowledge
from phantom.observation import Observation

rng = np.random.default_rng()

type MacroId = UnitTypeId | UpgradeId

type MacroAction = Mapping[Unit, Action]


@dataclass
class MacroPlan:
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0


class MacroState:
    def __init__(self, knowledge: Knowledge) -> None:
        self.knowledge = knowledge
        self.unassigned_plans = list[MacroPlan]()
        self.assigned_plans = dict[int, MacroPlan]()

    def make_composition(self, observation: Observation, composition: UnitComposition) -> Iterable[MacroPlan]:
        unit_priorities = dict[UnitTypeId, float]()
        for unit, target in composition.items():
            have = observation.count_actual(unit) + observation.count_pending(unit)
            planned = observation.count_planned(unit)
            if target < 1 or target <= have + planned:
                continue
            if any(observation.get_missing_requirements(unit)):
                continue
            priority = -have / target
            unit_priorities[unit] = priority
            if planned == 0:
                yield MacroPlan(unit, priority=priority)

        for plan in self.assigned_plans.values():
            if plan.priority == math.inf:
                continue
            if override_priority := unit_priorities.get(plan.item):
                plan.priority = override_priority

    def add(self, plan: MacroPlan) -> None:
        self.unassigned_plans.append(plan)
        logger.info(f"Adding {plan=}")

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self.assigned_plans.values(), self.unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return filter(lambda p: p.item == item, self.enumerate_plans())

    async def assign_unassigned_plans(self, obs: Observation, trainers: Units, blocked_positions: Set[Point]) -> None:
        trainer_set = set(trainers)
        for plan in list(self.unassigned_plans):
            if trainer := (await self.find_trainer(obs, trainer_set, plan.item, blocked_positions)):
                logger.info(f"Assigning {trainer=} for {plan=}")
                if plan in self.unassigned_plans:
                    self.unassigned_plans.remove(plan)
                self.assigned_plans[trainer.tag] = plan
                trainer_set.remove(trainer)

    def return_gatherers(self, obs: Observation) -> None:
        for unit in obs.get_units_from_role(UnitRole.PERSISTENT_BUILDER):
            if unit.tag not in self.assigned_plans and unit.tag not in obs.ordered_structures:
                logger.info(f"Returning {unit=} to gathering")
                obs.bot.mediator.assign_role(tag=unit.tag, role=UnitRole.GATHERING)

    async def step(self, obs: Observation, blocked_positions: Set[Point]) -> MacroAction:
        self.return_gatherers(obs)

        # TODO
        if len(self.unassigned_plans) > 100:
            obs.bot.add_replay_tag("overplanning")  # type: ignore
            self.unassigned_plans = []
        await self.assign_unassigned_plans(obs, obs.units, blocked_positions)  # TODO: narrow this down

        actions = dict[Unit, Action]()
        reserve = Cost()
        plans_prioritized = sorted(self.assigned_plans.items(), key=lambda p: p[1].priority, reverse=True)
        for _i, (tag, plan) in enumerate(plans_prioritized):
            # if plan.commanded and plan.executed:
            #     del self.assigned_plans[tag]
            #     logger.info(f"Successfully executed {plan=}")
            #     continue

            trainer = obs.unit_by_tag.get(tag)
            if not trainer:
                del self.assigned_plans[tag]
                self.unassigned_plans.append(plan)
                logger.info(f"{tag=} is MIA for {plan=}")
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
            # if plan.executed:
            #     logger.info(f"resetting target for {plan=}")
            #     plan.target = None
            #     plan.commanded = False
            #     plan.executed = False

            if (
                isinstance(plan.target, Point2)
                and not await obs.can_place_single(plan.item, plan.target)
                and plan.item not in {UnitTypeId.SPORECRAWLER}
            ):
                plan.target = None

            if not plan.target:
                try:
                    plan.target = await self.get_target(self.knowledge, obs, trainer, plan, blocked_positions)
                except PlacementNotFoundException:
                    continue

            cost = self.knowledge.cost.of(plan.item)
            eta = get_eta(obs, reserve, cost)

            if eta < math.inf:
                expected_income = obs.income * eta
                needs_to_reserve = Cost.max(Cost(), cost - expected_income)
                reserve += needs_to_reserve

            if trainer.type_id in WORKERS:
                obs.bot.mediator.assign_role(tag=trainer.tag, role=UnitRole.PERSISTENT_BUILDER)

            if trainer.is_carrying_resource:
                pass
            elif eta == 0.0:
                actions[trainer] = UseAbility(ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(AbilityId.HARVEST_RETURN)
                elif (obs.iteration % 10 == 0) and (action := await premove(obs, trainer, plan, eta)):
                    actions[trainer] = action
                # elif action := combat.fight_with(trainer):
                #     actions[trainer] = action

        return actions

    async def get_target(
        self, knowledge: Knowledge, obs: Observation, trainer: Unit, objective: MacroPlan, blocked_positions: Set[Point]
    ) -> Unit | Point2 | None:
        gas_type = GAS_BY_RACE[knowledge.race]
        if objective.item == gas_type:
            exclude_positions = {geyser.position for geyser in obs.gas_buildings}
            exclude_tags = {
                order.target
                for unit in obs.workers
                for order in unit.orders
                if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
            }
            exclude_tags.update({p.target.tag for p in self.planned_by_type(gas_type) if isinstance(p.target, Unit)})
            geysers = [
                geyser
                for geyser in obs.geyers_taken
                if (geyser.position not in exclude_positions and geyser.tag not in exclude_tags)
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
            position = await get_target_position(self.knowledge, obs, objective.item, blocked_positions)
            if not position:
                raise PlacementNotFoundException()
            return position
        else:
            return None

    async def find_trainer(
        self, obs: Observation, trainers: Iterable[Unit], item: MacroId, blocked_positions: Set[Point]
    ) -> Unit | None:
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

        if not any(trainers_filtered):
            return None

        if item == UnitTypeId.HATCHERY:
            target_expected = await get_target_position(self.knowledge, obs, item, blocked_positions)
            return min(
                trainers_filtered,
                key=lambda t: t.distance_to(target_expected),
            )

        return trainers_filtered[0]


async def premove(obs: Observation, unit: Unit, plan: MacroPlan, eta: float) -> Action | None:
    if not plan.target:
        return None
    target = plan.target.position
    distance = await obs.query_pathing(unit, target) or 0.0
    movement_eta = 1.5 + distance / (1.4 * unit.movement_speed)
    do_premove = eta <= movement_eta
    if not do_premove:
        return None
    if unit.distance_to(target) > 1e-3:
        return Move(target)
    return HoldPosition()


def get_eta(observation: Observation, reserve: Cost, cost: Cost) -> float:
    deficit = reserve + cost - observation.bank
    eta = deficit / observation.income
    return max(
        (
            0.0,
            eta.minerals if deficit.minerals > 0 and cost.minerals > 0 else 0.0,
            eta.vespene if deficit.vespene > 0 and cost.vespene > 0 else 0.0,
            eta.larva if deficit.larva > 0 and cost.larva > 0 else 0.0,
            eta.supply if deficit.supply > 0 and cost.supply > 0 else 0.0,
        )
    )


async def get_target_position(
    knowledge: Knowledge, obs: Observation, target: UnitTypeId, blocked_positions: Set[Point]
) -> Point2 | None:
    data = obs.unit_data(target)
    if target in {UnitTypeId.HATCHERY}:
        candidates = [b for b in knowledge.bases if b not in blocked_positions and b not in obs.townhall_at]
        if not candidates:
            return None
        loss_positions = {knowledge.in_mineral_line[b] for b in obs.bases_taken} | {obs.start_location}
        loss_positions_enemy = {knowledge.in_mineral_line[s] for s in knowledge.enemy_start_locations}

        async def loss_fn(p: Point2) -> float:
            distances = await obs.query_pathings([[Point2(p), Point2(q)] for q in loss_positions])
            distances_enemy = await obs.query_pathings([[Point2(p), Point2(q)] for q in loss_positions_enemy])
            return max(distances) - min(distances_enemy)

        c_min = candidates[0]
        loss_min = await loss_fn(c_min)
        for c in candidates[1:]:
            loss = await loss_fn(c)
            if loss < loss_min:
                loss_min = loss
                c_min = c
        return Point2(c_min).offset(HALF)

    def filter_base(b):
        if not (th := obs.townhall_at.get(b)):
            return False
        return th.is_ready

    if potential_bases := list(filter(filter_base, knowledge.bases)):
        base = random.choice(potential_bases)
        distance = rng.uniform(8, 12)
        mineral_line = Point2(knowledge.in_mineral_line[base])
        behind_mineral_line = Point2(base).towards(mineral_line, distance)
        position = Point2(base).towards_with_random_angle(behind_mineral_line, distance)
        offset = data.footprint_radius % 1
        position = position.rounded.offset((offset, offset))
        return position
    return None
