import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

import numpy as np
from ares.consts import GAS_BUILDINGS, TOWNHALL_TYPES, UnitRole
from cython_extensions import cy_closest_to, cy_distance_to
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

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

if TYPE_CHECKING:
    from phantom.main import PhantomBot

rng = np.random.default_rng()

type MacroId = UnitTypeId | UpgradeId


@dataclass
class MacroPlan:
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0


def _premove(unit: Unit, plan: MacroPlan, eta: float) -> Action | None:
    if not plan.target:
        return None
    target = plan.target.position
    distance = cy_distance_to(unit.position, target)
    movement_eta = 2.0 + distance / (1.4 * unit.movement_speed)
    if eta > movement_eta:
        return None
    if distance < 1e-3:
        return HoldPosition()
    return Move(target)


class Macro:
    def __init__(self, bot: "PhantomBot") -> None:
        self.bot = bot
        self.unassigned_plans = list[MacroPlan]()
        self.assigned_plans = dict[int, MacroPlan]()

    def make_composition(self, composition: UnitComposition) -> Iterable[MacroPlan]:
        unit_priorities = dict[UnitTypeId, float]()
        for unit, target in composition.items():
            have = self.bot.count_actual(unit) + self.bot.count_pending(unit)
            planned = self.bot.count_planned(unit)
            priority = -(have + 0.5) / max(1.0, target)
            unit_priorities[unit] = priority
            if target < 1 or target <= have + planned:
                continue
            if any(self.bot.get_missing_requirements(unit)):
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

    def get_actions(self) -> Mapping[Unit, Action]:
        for unit in self.bot.mediator.get_units_from_role(role=UnitRole.PERSISTENT_BUILDER):
            if unit.tag not in self.assigned_plans and unit.tag not in self.bot.ordered_structures:
                logger.info(f"Returning {unit=} to gathering")
                self.bot.mediator.assign_role(tag=unit.tag, role=UnitRole.GATHERING)

        # unassign all larvae
        for larva in self.bot.larva:
            if plan := self.assigned_plans.pop(larva.tag, None):
                self.unassigned_plans.append(plan)

        self._assign_unassigned_plans(self.bot.all_own_units)  # TODO: narrow this down

        actions = dict[Unit, Action]()
        reserve = Cost()
        plans_prioritized = sorted(self.assigned_plans.items(), key=lambda p: p[1].priority, reverse=True)
        for _i, (tag, plan) in enumerate(plans_prioritized):
            trainer = self.bot.unit_tag_dict.get(tag)
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

            if any(self.bot.get_missing_requirements(plan.item)):
                continue

            if isinstance(plan.target, Point2) and not self.bot.mediator.can_place_structure(
                position=plan.target,
                structure_type=plan.item,
                include_addon=False,
            ):
                plan.target = None

            if not plan.target:
                try:
                    plan.target = self._get_target(trainer, plan)
                except PlacementNotFoundException:
                    continue

            cost = self.bot.cost.of(plan.item)
            eta = self._get_eta(reserve, cost)

            if eta < math.inf:
                expected_income = self.bot.income * eta
                needs_to_reserve = Cost.max(Cost(), cost - expected_income)
                reserve += needs_to_reserve

            if trainer.type_id in WORKERS:
                self.bot.mediator.assign_role(tag=trainer.tag, role=UnitRole.PERSISTENT_BUILDER)

            if eta == 0.0:
                actions[trainer] = UseAbility(ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(AbilityId.HARVEST_RETURN)
                elif (self.bot.actual_iteration % 10 == 0) and (action := _premove(trainer, plan, eta)):
                    actions[trainer] = action

        return actions

    def _assign_unassigned_plans(self, trainers: Iterable[Unit]) -> None:
        for plan in sorted(self.unassigned_plans, key=lambda p: p.priority, reverse=True):
            if trainer := self._select_trainer(trainers, plan.item):
                if trainer.type_id != UnitTypeId.LARVA:
                    logger.info(f"Assigning {trainer=} for {plan=}")
                self.unassigned_plans.remove(plan)
                self.assigned_plans[trainer.tag] = plan

    def _get_target(self, trainer: Unit, plan: MacroPlan) -> Unit | Point2 | None:
        if plan.item in GAS_BUILDINGS:
            return self._get_gas_target(trainer.position)
        if (
            not (entry := MACRO_INFO.get(trainer.type_id))
            or not (data := entry.get(plan.item))
            or not data.get("requires_placement_position")
        ):
            return None
        if plan.item in TOWNHALL_TYPES:
            position = self._get_expansion_target()
        else:
            position = self._get_structure_target(plan.item)
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
                and trainer.tag not in self.assigned_plans
            )
        )

        return next(iter(trainers_filtered), None)

    def _get_gas_target(self, near: Point2) -> Unit:
        gas_type = GAS_BY_RACE[self.bot.race]
        exclude_positions = {geyser.position for geyser in self.bot.gas_buildings}
        exclude_tags = {
            order.target
            for unit in self.bot.workers
            for order in unit.orders
            if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
        }
        exclude_tags.update({p.target.tag for p in self.planned_by_type(gas_type) if isinstance(p.target, Unit)})
        geysers = [
            geyser
            for geyser in self.bot.all_taken_resources.vespene_geyser
            if (geyser.position not in exclude_positions and geyser.tag not in exclude_tags)
        ]
        if not geysers:
            raise PlacementNotFoundException()
        target = cy_closest_to(near, geysers)
        return target

    def _get_expansion_target(self) -> Point2:
        loss_positions = [self.bot.in_mineral_line[b] for b in self.bot.bases_taken]
        loss_positions_enemy = [self.bot.in_mineral_line[s] for s in self.bot.enemy_start_locations_rounded]

        def loss_fn(p: Point2) -> float:
            distances = map(lambda q: cy_distance_to(p, q), loss_positions)
            distances_enemy = map(lambda q: cy_distance_to(p, q), loss_positions_enemy)
            return max(distances, default=0.0) - min(distances_enemy, default=0.0)

        def is_viable(b: Point) -> bool:
            if b in self.bot.blocked_positions:
                return False
            if b in self.bot.structure_dict:
                return False
            return self.bot.mediator.is_position_safe(grid=self.bot.mediator.get_ground_grid, position=Point2(b))

        candidates = filter(is_viable, self.bot.bases)
        if target := min(candidates, key=loss_fn, default=None):
            return Point2(target).offset(HALF)

        raise PlacementNotFoundException()

    def _get_structure_target(self, structure_type: UnitTypeId) -> Point2:
        data = self.bot.game_data.units[structure_type.value]

        def filter_base(b):
            if th := self.bot.townhall_at.get(b):
                return th.is_ready
            return False

        if potential_bases := list(filter(filter_base, self.bot.bases)):
            base = random.choice(potential_bases)
            distance = rng.uniform(8, 12)
            mineral_line = Point2(self.bot.in_mineral_line[base])
            behind_mineral_line = Point2(base).towards(mineral_line, distance)
            position = Point2(base).towards_with_random_angle(behind_mineral_line, distance)
            offset = data.footprint_radius % 1
            position = position.rounded.offset((offset, offset))
            return position

        raise PlacementNotFoundException()

    def _get_eta(self, reserve: Cost, cost: Cost) -> float:
        bank = Cost(self.bot.bank.minerals, self.bot.bank.vespene, self.bot.bank.supply, min(1, self.bot.bank.larva))
        deficit = reserve + cost - bank
        eta = deficit / self.bot.income
        return max(
            (
                0.0,
                eta.minerals if deficit.minerals > 0 and cost.minerals > 0 else 0.0,
                eta.vespene if deficit.vespene > 0 and cost.vespene > 0 else 0.0,
                eta.larva if deficit.larva > 0 and cost.larva > 0 else 0.0,
                eta.supply if deficit.supply > 0 and cost.supply > 0 else 0.0,
            )
        )
