import math
import random
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

import numpy as np
from ares.consts import GAS_BUILDINGS, TOWNHALL_TYPES, UnitRole
from cython_extensions import cy_distance_to
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
from phantom.observation import Observation

if TYPE_CHECKING:
    from phantom.main import PhantomBot

rng = np.random.default_rng()

type MacroId = UnitTypeId | UpgradeId


@dataclass
class MacroPlan:
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0


class MacroState:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.unassigned_plans = list[MacroPlan]()
        self.assigned_plans = dict[int, MacroPlan]()

    def make_composition(self, observation: Observation, composition: UnitComposition) -> Iterable[MacroPlan]:
        unit_priorities = dict[UnitTypeId, float]()
        for unit, target in composition.items():
            have = observation.count_actual(unit) + observation.count_pending(unit)
            planned = observation.count_planned(unit)
            priority = -have / max(1.0, target)
            unit_priorities[unit] = priority
            if target < 1 or target <= have + planned:
                continue
            if any(observation.get_missing_requirements(unit)):
                continue
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

    def step(self, obs: Observation, blocked_positions: Set[Point]) -> "MacroAction":
        return MacroAction(self, obs, blocked_positions)


class MacroAction:
    def __init__(self, state: MacroState, obs: Observation, blocked_positions: Set[Point]) -> None:
        self.state = state
        self.obs = obs
        self.blocked_positions = blocked_positions

    def get_actions(self) -> Mapping[Unit, Action]:
        for unit in self.obs.get_units_from_role(UnitRole.PERSISTENT_BUILDER):
            if unit.tag not in self.state.assigned_plans and unit.tag not in self.obs.ordered_structures:
                logger.info(f"Returning {unit=} to gathering")
                self.obs.bot.mediator.assign_role(tag=unit.tag, role=UnitRole.GATHERING)

        # unassign all larvae
        for larva in self.state.bot.larva:
            if plan := self.state.assigned_plans.pop(larva.tag, None):
                self.state.unassigned_plans.append(plan)

        self.assign_unassigned_plans(self.obs.units)  # TODO: narrow this down

        actions = dict[Unit, Action]()
        reserve = Cost()
        plans_prioritized = sorted(self.state.assigned_plans.items(), key=lambda p: p[1].priority, reverse=True)
        for _i, (tag, plan) in enumerate(plans_prioritized):
            trainer = self.obs.unit_by_tag.get(tag)
            if not trainer:
                del self.state.assigned_plans[tag]
                self.state.unassigned_plans.append(plan)
                logger.info(f"{tag=} is MIA for {plan=}")
                continue

            if trainer.type_id == UnitTypeId.EGG:
                del self.state.assigned_plans[tag]
                self.state.unassigned_plans.append(plan)
                logger.info(f"{trainer} is an egg")
                continue

            ability = MACRO_INFO.get(trainer.type_id, {}).get(plan.item, {}).get("ability")
            if not ability:
                del self.state.assigned_plans[tag]
                self.state.unassigned_plans.append(plan)
                logger.info(f"{trainer=} is unable to execute {plan=}")
                continue

            if any(self.obs.get_missing_requirements(plan.item)):
                continue

            if (
                isinstance(plan.target, Point2)
                and not self.obs.can_place_single(plan.item, plan.target)
                and plan.item not in {UnitTypeId.SPORECRAWLER}
            ):
                plan.target = None

            if not plan.target:
                try:
                    plan.target = self.get_target(self.obs, trainer, plan, self.blocked_positions)
                except PlacementNotFoundException:
                    continue

            cost = self.state.bot.cost.of(plan.item)
            eta = self.get_eta(reserve, cost)

            if eta < math.inf:
                expected_income = self.obs.income * eta
                needs_to_reserve = Cost.max(Cost(), cost - expected_income)
                reserve += needs_to_reserve

            if trainer.type_id in WORKERS:
                self.obs.bot.mediator.assign_role(tag=trainer.tag, role=UnitRole.PERSISTENT_BUILDER)

            if eta == 0.0:
                actions[trainer] = UseAbility(ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(AbilityId.HARVEST_RETURN)
                elif (self.obs.iteration % 10 == 0) and (action := premove(trainer, plan, eta)):
                    actions[trainer] = action

        return actions

    def assign_unassigned_plans(self, trainers: Units) -> None:
        trainer_set = set(trainers)
        for plan in sorted(self.state.unassigned_plans, key=lambda p: p.priority, reverse=True):
            if trainer := self._select_trainer(trainer_set, plan.item):
                if trainer.type_id != UnitTypeId.LARVA:
                    logger.info(f"Assigning {trainer=} for {plan=}")
                if plan in self.state.unassigned_plans:
                    self.state.unassigned_plans.remove(plan)
                self.state.assigned_plans[trainer.tag] = plan
                trainer_set.remove(trainer)

    def get_target(
        self, obs: Observation, trainer: Unit, objective: MacroPlan, blocked_positions: Set[Point]
    ) -> Unit | Point2 | None:
        if objective.item in GAS_BUILDINGS:
            return self.get_gas_target(obs)
        if (
            not (entry := MACRO_INFO.get(trainer.type_id))
            or not (data := entry.get(objective.item))
            or not data.get("requires_placement_position")
        ):
            return None
        if objective.item in TOWNHALL_TYPES:
            position = self.get_expansion_target(obs, blocked_positions)
        else:
            position = self.get_tech_target(obs, objective.item)
        if not position:
            raise PlacementNotFoundException()
        return position

    def _select_trainer(
        self,
        all_trainers: Iterable[Unit],
        item: MacroId,
    ) -> Unit | None:
        trainer_types = ITEM_TRAINED_FROM_WITH_EQUIVALENTS[item]

        trainers_filtered = (
            trainer
            for trainer in all_trainers
            if (
                trainer.type_id in trainer_types
                and trainer.is_ready
                and (trainer.is_idle or not trainer.is_structure)
                and trainer.tag not in self.state.assigned_plans
            )
        )

        return next(iter(trainers_filtered), None)

    def get_gas_target(self, obs: Observation) -> Unit:
        gas_type = GAS_BY_RACE[self.state.bot.race]
        exclude_positions = {geyser.position for geyser in obs.gas_buildings}
        exclude_tags = {
            order.target
            for unit in obs.workers
            for order in unit.orders
            if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
        }
        exclude_tags.update({p.target.tag for p in self.state.planned_by_type(gas_type) if isinstance(p.target, Unit)})
        geysers = [
            geyser
            for geyser in obs.geyers_taken
            if (geyser.position not in exclude_positions and geyser.tag not in exclude_tags)
        ]
        if target := min(geysers, key=lambda g: g.tag, default=None):
            return target
        raise PlacementNotFoundException()

    def get_expansion_target(self, obs: Observation, blocked_positions: Set[Point]) -> Point2:
        loss_positions = [self.state.bot.in_mineral_line[b] for b in obs.bases_taken]
        loss_positions_enemy = [self.state.bot.in_mineral_line[s] for s in self.state.bot.enemy_start_locations_rounded]

        def loss_fn(p: Point2) -> float:
            distances = map(lambda q: cy_distance_to(p, q), loss_positions)
            distances_enemy = map(lambda q: cy_distance_to(p, q), loss_positions_enemy)
            return max(distances, default=0.0) - min(distances_enemy, default=0.0)

        candidates = (b for b in self.state.bot.bases if b not in blocked_positions and b not in obs.townhall_at)
        if target := min(candidates, key=loss_fn, default=None):
            return Point2(target).offset(HALF)

        raise PlacementNotFoundException()

    def get_tech_target(self, obs: Observation, target: UnitTypeId) -> Point2:
        data = obs.unit_data(target)

        def filter_base(b):
            if th := obs.townhall_at.get(b):
                return th.is_ready
            return False

        if potential_bases := list(filter(filter_base, self.state.bot.bases)):
            base = random.choice(potential_bases)
            distance = rng.uniform(8, 12)
            mineral_line = Point2(self.state.bot.in_mineral_line[base])
            behind_mineral_line = Point2(base).towards(mineral_line, distance)
            position = Point2(base).towards_with_random_angle(behind_mineral_line, distance)
            offset = data.footprint_radius % 1
            position = position.rounded.offset((offset, offset))
            return position

        raise PlacementNotFoundException()

    def get_eta(self, reserve: Cost, cost: Cost) -> float:
        bank = Cost(self.obs.bank.minerals, self.obs.bank.vespene, self.obs.bank.supply, min(1, self.obs.bank.larva))
        deficit = reserve + cost - bank
        eta = deficit / self.obs.income
        return max(
            (
                0.0,
                eta.minerals if deficit.minerals > 0 and cost.minerals > 0 else 0.0,
                eta.vespene if deficit.vespene > 0 and cost.vespene > 0 else 0.0,
                eta.larva if deficit.larva > 0 and cost.larva > 0 else 0.0,
                eta.supply if deficit.supply > 0 and cost.supply > 0 else 0.0,
            )
        )


def premove(unit: Unit, plan: MacroPlan, eta: float) -> Action | None:
    if not plan.target:
        return None
    target = plan.target.position
    distance = cy_distance_to(unit.position, target)
    movement_eta = 1.5 + distance / (1.4 * unit.movement_speed)
    if eta > movement_eta:
        return None
    if distance < 1e-3:
        return HoldPosition()
    return Move(target)
