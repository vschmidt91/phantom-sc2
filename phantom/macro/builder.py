import math
import random
from collections.abc import Callable, Iterable, Mapping, Set
from dataclasses import dataclass
from itertools import chain
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
    HALF,
    ITEM_BY_ABILITY,
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
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0
    allow_replacement: bool = True


class BuilderParameters:
    def __init__(self, sampler: ParameterSampler) -> None:
        self.tech_priority_offset = sampler.add(Prior(-1.0, 0.01))
        self.tech_priority_scale = sampler.add(Prior(0.5, 0.01, min=0))


class Builder:
    def __init__(self, bot: "PhantomBot", parameters: BuilderParameters) -> None:
        self.bot = bot
        self.parameters = parameters
        self._unassigned_plans = list[MacroPlan]()
        self._assigned_plans = dict[int, MacroPlan]()
        self.min_priority = -1.0

    def make_composition(self, composition: UnitComposition) -> Iterable[MacroPlan]:
        unit_priorities = dict[UnitTypeId, float]()
        for unit, target in composition.items():
            have = self.bot.count_actual(unit) + self.bot.count_pending(unit)
            planned = self.bot.count_planned(unit)
            priority = -(have + 0.5) / max(1.0, math.ceil(target))
            unit_priorities[unit] = priority
            if target < 1 or target <= have + planned:
                continue
            if any(self.bot.get_missing_requirements(unit)):
                continue
            if planned == 0:
                yield MacroPlan(unit, priority=priority)

        for plan in self._assigned_plans.values():
            if plan.priority == math.inf:
                continue
            if override_priority := unit_priorities.get(plan.item):
                plan.priority = override_priority

    def debug_draw_plans(self) -> None:
        plans = list(chain(
            ((None, p) for p in self._unassigned_plans),
            self._assigned_plans.items(),
        ))
        plans_sorted = sorted(plans, key=lambda p: p[1].priority, reverse=True)
        for i, (tag, plan) in enumerate(plans_sorted):
            trainer = self.bot.unit_tag_dict.get(tag)
            self._debug_draw_plan(trainer, plan, index=i)

    def add(self, plan: MacroPlan) -> None:
        self._unassigned_plans.append(plan)
        logger.info(f"Adding {plan}")

    def get_planned_cost(self) -> Cost:
        cost = Cost()
        for plan in self._unassigned_plans:
            cost += self.bot.cost.of(plan.item)
        for plan in self._assigned_plans.values():
            cost += self.bot.cost.of(plan.item)
        return cost

    @property
    def assigned_tags(self) -> Set[int]:
        return self._assigned_plans.keys()

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self._assigned_plans.values(), self._unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return filter(lambda p: p.item == item, self.enumerate_plans())

    def expand(self) -> Iterable[MacroPlan]:
        worker_max = self.bot.max_harvesters + 22 * self.bot.count_pending(UnitTypeId.HATCHERY)
        saturation = self.bot.supply_workers / max(1, worker_max)
        saturation = max(0.0, min(1.0, saturation))

        priority = 3 * (saturation - 1)

        for plan in self._assigned_plans.values():
            if plan.item == UnitTypeId.HATCHERY:
                plan.priority = priority

        if priority < -1:
            return
        if self.bot.count_planned(UnitTypeId.HATCHERY) > 0:
            return

        yield MacroPlan(UnitTypeId.HATCHERY, priority=priority)

    def make_upgrades(
        self, composition: UnitComposition, upgrade_filter: Callable[[UpgradeId], bool]
    ) -> Iterable[MacroPlan]:
        upgrade_weights = dict[UpgradeId, float]()
        for unit, count in composition.items():
            cost = self.bot.cost.of(unit)
            total_cost = (cost.minerals + 2 * cost.vespene) * (0.5 if unit == UnitTypeId.ZERGLING else 1.0)
            for upgrade in self.bot.upgrades_by_unit(unit):
                upgrade_weights[upgrade] = upgrade_weights.get(upgrade, 0.0) + count * total_cost

        # strategy specific filter
        upgrade_weights = {k: v for k, v in upgrade_weights.items() if upgrade_filter(k)}

        if not upgrade_weights:
            return
        total = max(upgrade_weights.values())
        if total == 0:
            return

        upgrade_priorities = {
            k: max(
                -1, self.parameters.tech_priority_offset.value + self.parameters.tech_priority_scale.value * v / total
            )
            for k, v in upgrade_weights.items()
        }

        for plan in self.enumerate_plans():
            if priority := upgrade_priorities.get(plan.item):
                plan.priority = priority

        for upgrade, priority in upgrade_priorities.items():
            if self.bot.count_actual(upgrade) or self.bot.count_pending(upgrade) or self.bot.count_planned(upgrade):
                continue
            yield MacroPlan(upgrade, priority=priority)

    def on_step(self) -> None:
        # detect executed plans
        list(chain[Unit](self.bot.larva, self.bot.eggs))
        for action in self.bot.state.actions_unit_commands:
            if action.exact_id not in EXCLUDE_ABILTIES and (item := ITEM_BY_ABILITY.get(action.exact_id)):
                for tag in action.unit_tags:
                    unit = self.bot.unit_tag_dict.get(tag) or self.bot._units_previous_map.get(tag)
                    if not unit:
                        self.bot.add_replay_tag("trainer_not_found")
                        logger.error("Trainer not found")
                        continue
                    if unit.type_id == UnitTypeId.DRONE:
                        if not unit:
                            self.bot.add_replay_tag("trainer_not_found")
                            logger.error("Trainer not found")
                            continue
                        if plan := self._assigned_plans.get(unit.tag):
                            if plan.item != item:
                                logger.error(f"Unplanned {action}")
                            del self._assigned_plans[unit.tag]
                        else:
                            logger.error(f"Unplanned {action}")
                    else:
                        plan_candidates = [p for p in self._unassigned_plans if p.item == item]
                        plan_candidates.sort(key=lambda p: p.priority, reverse=True)
                        if plan_candidates:
                            self._unassigned_plans.remove(plan_candidates[0])
                        else:
                            logger.error(f"Unplanned {action}")

        self._cancel_low_priority_plans(self.min_priority)

        self._assign_unassigned_worker_plans()

    def get_actions(self) -> Mapping[Unit, Action]:
        actions = dict[Unit, Action]()
        reserve = Cost()

        all_trainers = [
            trainer
            for trainer in self.bot.all_own_units
            if (
                trainer.type_id in TRAINER_TYPES
                and trainer.is_ready
                and (trainer.is_idle if trainer.is_structure else True)
            )
        ]

        all_plans = list[tuple[int | None, MacroPlan]]()
        all_plans.extend((None, plan) for plan in self._unassigned_plans)
        all_plans.extend(self._assigned_plans.items())
        all_plans.sort(key=lambda p: p[1].priority, reverse=True)

        for _i, (tag, plan) in enumerate(all_plans):
            trainer = self._select_trainer(all_trainers, plan.item) if tag is None else self.bot.unit_tag_dict.get(tag)

            if trainer is None:
                if tag is not None:
                    del self._assigned_plans[tag]
                continue

            ability = MACRO_INFO[trainer.type_id][plan.item]["ability"]

            if isinstance(plan.target, Point2) and (
                not self.bot.mediator.can_place_structure(
                    position=plan.target,
                    structure_type=plan.item,
                )
                or to_point(plan.target) in self.bot.blocked_positions
            ):
                if plan.allow_replacement:
                    plan.target = None
                else:
                    logger.info(f"cannot place {plan} and not allowed to replace, cancelling.")
                    if tag is not None:
                        del self._assigned_plans[tag]
                    continue

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

            if eta == 0.0:
                actions[trainer] = UseAbility(ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(AbilityId.HARVEST_RETURN)
                elif (self.bot.actual_iteration % 10 == 0) and (action := self._premove(trainer, plan, eta)):
                    actions[trainer] = action

        return actions

    def _cancel_low_priority_plans(self, min_priority: float) -> None:
        for plan in list(self._unassigned_plans):
            if plan.priority < min_priority:
                self._unassigned_plans.remove(plan)
        for tag, plan in list(self._assigned_plans.items()):
            if plan.priority < min_priority:
                del self._assigned_plans[tag]

    def _assign_unassigned_worker_plans(self) -> None:
        trainers = self.bot.workers
        for plan in sorted(self._unassigned_plans, key=lambda p: p.priority, reverse=True):
            if trainer := self._select_trainer(trainers, plan.item):
                if trainer.type_id != UnitTypeId.LARVA:
                    logger.info(f"Assigning {plan} to {trainer}")
                self._unassigned_plans.remove(plan)
                self._assigned_plans[trainer.tag] = plan

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
        return next(
            (
                trainer
                for trainer in all_trainers
                if trainer.type_id in trainer_types and trainer.tag not in self._assigned_plans
            ),
            None,
        )

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
        plan: MacroPlan,
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

        text = f"{plan.item.name} {round(plan.priority, 2)}"

        for position in positions:
            self.bot.client.debug_text_world(text, position, color=font_color, size=font_size)

        if len(positions) == 2:
            position_from, position_to = positions
            position_from += Point3((0.0, 0.0, 0.1))
            position_to += Point3((0.0, 0.0, 0.1))
            self.bot.client.debug_line_out(position_from, position_to, color=font_color)

        self.bot.client.debug_text_screen(
            f"{1 + index} {round(plan.priority, 2)} {plan.item.name}", (0.01, 0.1 + 0.01 * index)
        )


class PlacementNotFoundException(Exception):
    pass
