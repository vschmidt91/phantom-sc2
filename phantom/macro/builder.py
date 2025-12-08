import math
import random
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares.consts import GAS_BUILDINGS, TOWNHALL_TYPES
from cython_extensions import cy_closest_to, cy_distance_to
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.unit import Unit

from phantom.common.action import Action, HoldPosition, Move, UseAbility
from phantom.common.constants import (
    BUILDER_ABILITIES,
    HALF,
    ITEM_TRAINED_FROM_WITH_EQUIVALENTS,
    MACRO_INFO,
    TRAINER_TYPES,
)
from phantom.common.cost import Cost
from phantom.common.parameter_sampler import ParameterSampler, Prior
from phantom.common.unit_composition import UnitComposition
from phantom.common.utils import MacroId, Point, to_point

if TYPE_CHECKING:
    from phantom.main import PhantomBot

rng = np.random.default_rng()

EXCLUDE_ABILTIES = {
    AbilityId.BUILD_CREEPTUMOR_TUMOR,
    AbilityId.BUILD_CREEPTUMOR_QUEEN,
    AbilityId.SPAWNCHANGELING_SPAWNCHANGELING,
}


@dataclass
class MacroPlan:
    tag: int | None = None
    target: Unit | Point2 | None = None
    allow_replacement: bool = True


class BuilderParameters:
    def __init__(self, sampler: ParameterSampler) -> None:
        self.tech_priority_offset = sampler.add(Prior(-1.0, 0.01))
        self.tech_priority_scale = sampler.add(Prior(0.5, 0.01, min=0))


class Builder:
    def __init__(self, bot: "PhantomBot", parameters: BuilderParameters) -> None:
        self.bot = bot
        self.parameters = parameters
        self._plans = dict[UnitTypeId, MacroPlan]()
        self.min_priority = -1.0

    def get_priorities(self, composition: UnitComposition) -> Mapping[UnitTypeId, float]:
        priorities = dict[UnitTypeId, float]()
        for unit, target in composition.items():
            have = self.bot.count_actual(unit) + self.bot.count_pending(unit)
            planned = self.bot.count_planned(unit)
            priority = -(have + 0.5) / max(1.0, math.ceil(target))
            if target < 1 or target <= have + planned:
                continue
            if any(self.bot.get_missing_requirements(unit)):
                continue
            priorities[unit] = priority
        return priorities

    def debug_draw_plans(self, priorities: Mapping[MacroId, float]) -> None:
        plans_sorted = sorted(self._plans.items(), key=lambda p: priorities.get(p[0], 0.0), reverse=True)
        for i, (item, plan) in enumerate(plans_sorted):
            trainer = self.bot.unit_tag_dict.get(plan.tag) if plan.tag else None
            priority = priorities.get(item, 0.0)
            self._debug_draw_plan(trainer, item, plan, priority, index=i)

    def add(self, item: UnitTypeId, plan: MacroPlan) -> None:
        self._plans[item] = plan
        logger.info(f"Planning {item} through {plan}")

    def get_planned_cost(self) -> Cost:
        return sum(map(self.bot.cost.of, self._plans), Cost())

    @property
    def assigned_tags(self) -> Set[int]:
        return {p.tag for p in self._plans.values() if p.tag is not None}

    def expansion_priority(self) -> float:
        worker_max = self.bot.max_harvesters + 22 * self.bot.count_pending(UnitTypeId.HATCHERY)
        saturation = self.bot.supply_workers / max(1, worker_max)
        saturation = max(0.0, min(1.0, saturation))
        priority = 3 * (saturation - 1)
        return priority

    def make_upgrades(
        self, composition: UnitComposition, upgrade_filter: Callable[[UpgradeId], bool]
    ) -> Mapping[UpgradeId, float]:
        upgrade_weights = dict[UpgradeId, float]()
        for unit, count in composition.items():
            cost = self.bot.cost.of(unit)
            total_cost = (cost.minerals + 2 * cost.vespene) * (0.5 if unit == UnitTypeId.ZERGLING else 1.0)
            for upgrade in self.bot.upgrades_by_unit(unit):
                upgrade_weights[upgrade] = upgrade_weights.get(upgrade, 0.0) + count * total_cost

        # strategy specific filter
        upgrade_weights = {k: v for k, v in upgrade_weights.items() if upgrade_filter(k)}

        if not upgrade_weights:
            return {}
        total = max(upgrade_weights.values())
        if total == 0:
            return {}

        upgrade_priorities = {
            k: max(
                -1, self.parameters.tech_priority_offset.value + self.parameters.tech_priority_scale.value * v / total
            )
            for k, v in upgrade_weights.items()
        }

        return upgrade_priorities

    def on_step(self) -> None:
        for ability, build in BUILDER_ABILITIES.items():
            if self.bot.actions_by_ability[ability]:
                self._plans.pop(build, None)
        self._assign_unassigned_worker_plans()

    def get_actions(self, priorities: Mapping[MacroId, float]) -> Mapping[Unit, Action]:
        actions = dict[Unit, Action]()
        reserve = Cost()
        all_trainers = {
            trainer.tag: trainer
            for trainer in self.bot.all_own_units
            if (
                trainer.type_id in TRAINER_TYPES
                and trainer.is_ready
                and (trainer.is_idle if trainer.is_structure else True)
            )
        }

        plans = dict[MacroId, MacroPlan | None](self._plans)
        plans.update({item: None for item in priorities if item not in self._plans})

        plans_sorted = sorted(plans.items(), key=lambda p: priorities.get(p[0], 0.0), reverse=True)
        for item, plan in plans_sorted:
            if plan:
                trainer = self.bot.unit_tag_dict.get(plan.tag) if plan.tag else None
                if trainer is None:
                    plan.tag = None
                    continue

                if isinstance(plan.target, Point2) and (
                    not self.bot.mediator.can_place_structure(
                        position=plan.target,
                        structure_type=item,
                    )
                    or to_point(plan.target) in self.bot.blocked_positions
                ):
                    if plan.allow_replacement:
                        plan.target = None
                    else:
                        logger.info(f"cannot place {plan} and not allowed to replace, cancelling.")
                        self._plans.pop(item, None)
                        continue

                if not plan.target:
                    try:
                        plan.target = self._get_target(trainer, item)
                    except PlacementNotFoundException:
                        continue
            else:
                trainer = next(
                    (t for t in all_trainers.values() if t.type_id in ITEM_TRAINED_FROM_WITH_EQUIVALENTS[item]),
                    None,
                )

            if not trainer:
                continue

            all_trainers.pop(trainer.tag, None)

            cost = self.bot.cost.of(item)
            eta = self._get_eta(reserve, cost)

            if eta < math.inf:
                expected_income = self.bot.income * eta
                needs_to_reserve = Cost.max(Cost(), cost - expected_income)
                reserve += needs_to_reserve

            target = plan.target if plan else None
            if eta == 0.0:
                ability = MACRO_INFO[trainer.type_id][item]["ability"]
                actions[trainer] = UseAbility(ability, target=target)
            elif target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(AbilityId.HARVEST_RETURN)
                elif (self.bot.actual_iteration % 10 == 0) and (action := self._premove(trainer, plan, eta)):
                    actions[trainer] = action

        return actions

    def _assign_unassigned_worker_plans(self) -> None:
        assigned_tags = {p.tag for p in self._plans.values()}
        workers = {w.tag: w for w in self.bot.workers if w.tag not in assigned_tags}
        if not workers:
            return
        for plan in self._plans.values():
            if plan.tag:
                continue
            tag = random.choice(list(workers))
            plan.tag = tag
            workers.pop(tag, None)
            logger.info(f"Assigning {plan} to worker {tag}")

    def _get_target(self, trainer: Unit, item: UnitTypeId) -> Unit | Point2 | None:
        if item in GAS_BUILDINGS:
            return self._get_gas_target(trainer.position)
        if (
            not (entry := MACRO_INFO.get(trainer.type_id))
            or not (data := entry.get(item))
            or not data.get("requires_placement_position")
        ):
            return None
        position = self._get_expansion_target() if item in TOWNHALL_TYPES else self._get_structure_target(item)
        if not position:
            raise PlacementNotFoundException()
        return position

    def _get_gas_target(self, near: Point2) -> Unit:
        geysers = [
            geyser
            for geyser in self.bot.all_taken_geysers
            if (to_point(geyser.position) not in self.bot.structure_dict)
        ]
        if not geysers:
            raise PlacementNotFoundException()
        target = cy_closest_to(near, geysers)
        return target

    def _get_expansion_target(self) -> Point2:
        loss_positions = [b.mineral_center for b in self.bot.bases_taken.values()]
        loss_positions_enemy = self.bot.enemy_start_locations

        def loss_fn(p: Point2) -> float:
            distances = map(lambda q: cy_distance_to(p, q), loss_positions)
            distances_enemy = map(lambda q: cy_distance_to(p, q), loss_positions_enemy)
            return max(distances, default=0.0) - min(distances_enemy, default=0.0)

        def is_viable(b: Point) -> bool:
            if b in self.bot.blocked_positions:
                return False
            if b in self.bot.structure_dict:
                return False
            p = Point2(b).offset((0.5, 0.5))
            if not self.bot.mediator.is_position_safe(grid=self.bot.ground_grid, position=p):
                return False
            return self.bot.mediator.can_place_structure(position=p, structure_type=UnitTypeId.HATCHERY)

        candidates = filter(is_viable, self.bot.expansions)
        if target := min(candidates, key=loss_fn, default=None):
            return Point2(target).offset(HALF)

        raise PlacementNotFoundException()

    def _get_structure_target(self, structure_type: UnitTypeId, num_attempts: int = 100) -> Point2:
        if not any(self.bot.bases_taken):
            raise PlacementNotFoundException()

        data = self.bot.game_data.units[structure_type.value]
        offset = data.footprint_radius % 1

        bases = list(self.bot.bases_taken.items())
        for _ in range(num_attempts):
            base, expansion = random.choice(bases)
            distance = rng.uniform(8, 12)
            mineral_line = Point2(expansion.mineral_center)
            position = expansion.townhall_position.towards_with_random_angle(mineral_line, distance)
            position = position.rounded.offset((offset, offset))
            if self.bot.mediator.can_place_structure(
                position=position,
                structure_type=structure_type,
            ):
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

    def _premove(self, unit: Unit, plan: MacroPlan, eta: float) -> Action | None:
        if plan.target is None:
            return None
        target = plan.target.position
        distance = cy_distance_to(unit.position, target)
        movement_eta = (4 / 3) * distance / (1.4 * unit.real_speed)
        if eta > movement_eta:
            return None
        if distance < 1e-3:
            return HoldPosition()
        self.bot.mediator.find_path_next_point(
            start=unit.position,
            target=target,
            grid=self.bot.ground_grid,
            smoothing=True,
        )
        return Move(target)

    def _debug_draw_plan(
        self,
        unit: Unit | None,
        item: MacroId,
        plan: MacroPlan,
        priority: float,
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
            height = self.bot.get_terrain_z_height(plan.target)
            positions.append(Point3((plan.target.x, plan.target.y, height)))

        if unit:
            height = self.bot.get_terrain_z_height(unit)
            positions.append(Point3((unit.position.x, unit.position.y, height)))

        text = f"{item.name} {round(priority, 2)}"

        for position in positions:
            self.bot.client.debug_text_world(text, position, color=font_color, size=font_size)

        if len(positions) == 2:
            position_from, position_to = positions
            position_from += Point3((0.0, 0.0, 0.1))
            position_to += Point3((0.0, 0.0, 0.1))
            self.bot.client.debug_line_out(position_from, position_to, color=font_color)

        self.bot.client.debug_text_screen(f"{1 + index} {round(priority, 2)} {item.name}", (0.01, 0.1 + 0.01 * index))


class PlacementNotFoundException(Exception):
    pass
