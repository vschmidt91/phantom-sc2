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

from phantom.combat.action import CombatAction
from phantom.common.action import Action, HoldPosition, Move, UseAbility
from phantom.common.constants import (
    ALL_MACRO_ABILITIES,
    GAS_BY_RACE,
    ITEM_BY_ABILITY,
    ITEM_TRAINED_FROM_WITH_EQUIVALENTS,
    MACRO_INFO,
    HALF,
)
from phantom.common.cost import Cost
from phantom.common.unit_composition import UnitComposition
from phantom.common.utils import PlacementNotFoundException, Point
from phantom.observation import Observation

MacroId: TypeAlias = UnitTypeId | UpgradeId

MacroAction: TypeAlias = dict[Unit, Action]


@dataclass
class MacroPlan:
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0
    premoved = False
    executed = False
    commanded = False


class MacroState:
    unassigned_plans = list[MacroPlan]()
    assigned_plans = dict[int, MacroPlan]()

    def make_composition(self, observation: Observation, composition: UnitComposition) -> Iterable[MacroPlan]:
        if 200 <= observation.supply_used:
            return
        for unit in composition:
            target = composition[unit]
            have = observation.count(unit)
            if target < 1:
                continue
            elif target <= have:
                continue
            if any(observation.get_missing_requirements(unit)):
                continue
            priority = -observation.count(unit, include_planned=False) / target
            if any(self.planned_by_type(unit)):
                for plan in self.planned_by_type(unit):
                    if plan.priority == math.inf:
                        continue
                    plan.priority = priority
                    break
            else:
                yield MacroPlan(unit, priority=priority)

    def add(self, plan: MacroPlan) -> None:
        self.unassigned_plans.append(plan)
        logger.info(f"Adding {plan=}")

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self.assigned_plans.values(), self.unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return (plan for plan in self.enumerate_plans() if plan.item == item)

    async def assign_unassigned_plans(self, obs: Observation, trainers: Units) -> None:
        trainer_set = set(trainers)
        for plan in list(self.unassigned_plans):
            if trainer := (await self.find_trainer(obs, trainer_set, plan.item)):
                logger.info(f"Assigning {trainer=} for {plan=}")
                if plan in self.unassigned_plans:
                    self.unassigned_plans.remove(plan)
                self.assigned_plans[trainer.tag] = plan
                trainer_set.remove(trainer)

    async def step(self, obs: Observation, blocked_positions: set[Point], combat: CombatAction) -> MacroAction:
        self.handle_actions(obs)
        await self.assign_unassigned_plans(obs, obs.units)  # TODO: narrow this down

        actions = dict[Unit, Action]()
        reserve = obs.cost.zero
        plans_prioritized = sorted(self.assigned_plans.items(), key=lambda p: p[1].priority, reverse=True)
        for i, (tag, plan) in enumerate(plans_prioritized):
            if plan.commanded and plan.executed:
                del self.assigned_plans[tag]
                logger.info(f"Successfully executed {plan=}")
                continue

            trainer = obs.unit_by_tag.get(tag)
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
                if not await obs.can_place_single(plan.item, plan.target):
                    plan.target = None
                    plan.commanded = False
                    plan.executed = False

            if not plan.target:
                try:
                    plan.target = await self.get_target(obs, trainer, plan, blocked_positions)
                except PlacementNotFoundException:
                    continue

            cost = obs.cost.of(plan.item)
            eta = get_eta(obs, reserve, cost)

            if eta < math.inf:
                expected_income = obs.income * eta
                needs_to_reserve = Cost.max(obs.cost.zero, cost - expected_income)
                reserve += needs_to_reserve

            if eta == 0.0:
                plan.commanded = True
                actions[trainer] = UseAbility(trainer, ability, target=plan.target)
            elif plan.target:
                if trainer.is_carrying_resource:
                    actions[trainer] = UseAbility(trainer, AbilityId.HARVEST_RETURN)
                elif action := await premove(obs, trainer, plan, eta):
                    plan.premoved = False
                    actions[trainer] = action
                elif action := combat.fight_with(trainer):
                    actions[trainer] = action

        return actions

    async def get_target(
        self, obs: Observation, trainer: Unit, objective: MacroPlan, blocked_positions: set[Point]
    ) -> Unit | Point2 | None:
        gas_type = GAS_BY_RACE[obs.race]
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
            position = await get_target_position(obs, objective.item, blocked_positions)
            if not position:
                raise PlacementNotFoundException()
            return position
        else:
            return None

    async def find_trainer(self, obs: Observation, trainers: Iterable[Unit], item: MacroId) -> Unit | None:
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

        if item == UnitTypeId.HATCHERY:
            target_expected = await get_target_position(obs, item, set())
            return min(
                trainers_filtered,
                key=lambda t: t.distance_to(target_expected) if t else 0,
                default=None,
            )

        if any(trainers_filtered):
            # trainers_filtered.sort(key=lambda t: t.tag)
            return trainers_filtered[0]

        return None

    def handle_actions(self, obs: Observation) -> None:
        for tag, action in obs.actions_unit_commands.items():
            self.handle_action(obs, action, tag)

    def handle_action(self, obs: Observation, action: ActionRawUnitCommand, tag: int) -> None:
        unit = obs.unit_by_tag.get(tag)
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


async def premove(obs: Observation, unit: Unit, plan: MacroPlan, eta: float) -> Action | None:
    if not plan.target:
        return None
    target = plan.target.position
    if plan.premoved:
        do_premove = True
    else:
        distance = await obs.query_pathing(unit, target) or 0.0
        movement_eta = 1.5 + distance / (1.4 * unit.movement_speed)
        do_premove = eta <= movement_eta
    if not do_premove:
        return None
    plan.premoved = True
    if 1e-3 < unit.distance_to(target):
        return Move(unit, target)
    return HoldPosition(unit)


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


async def get_target_position(obs: Observation, target: UnitTypeId, blocked_positions: set[Point]) -> Point2 | None:
    data = obs.unit_data(target)
    if target in {UnitTypeId.HATCHERY}:
        candidates = [b for b in obs.bases if b not in blocked_positions and b not in obs.townhall_at]
        if not candidates:
            return None
        loss_positions = {obs.in_mineral_line(b) for b in obs.bases_taken} | {obs.start_location}
        loss_positions_enemy = {obs.in_mineral_line(s) for s in obs.enemy_start_locations}

        async def loss_fn(p: Point2) -> float:
            distances = await obs.query_pathings([[p, q] for q in loss_positions])
            distances_enemy = await obs.query_pathings([[p, q] for q in loss_positions_enemy])
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
        if not th.is_ready:
            return False
        return True

    if potential_bases := list(filter(filter_base, obs.bases)):
        base = random.choice(potential_bases)
        position = Point2(base).offset(HALF).towards_with_random_angle(obs.behind_mineral_line(base), 10)
        offset = data.footprint_radius % 1
        position = position.rounded.offset((offset, offset))
        return position
    return None
