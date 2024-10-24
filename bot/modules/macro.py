from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import cached_property, cmp_to_key
from itertools import chain
from typing import TYPE_CHECKING, Iterable, TypeAlias

from action import Action, HoldPosition, Move, UseAbility
from ares import AresBot
from sc2.data import race_townhalls
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ..components.component import Component
from ..constants import (
    ALL_MACRO_ABILITIES,
    GAS_BY_RACE,
    ITEM_TRAINED_FROM_WITH_EQUIVALENTS,
    MACRO_INFO,
    REQUIREMENTS,
    WITH_TECH_EQUIVALENTS,
    ZERG_ARMOR_UPGRADES,
    ZERG_FLYER_ARMOR_UPGRADES,
    ZERG_FLYER_UPGRADES,
    ZERG_MELEE_UPGRADES,
    ZERG_RANGED_UPGRADES,
)
from ..cost import Cost
from ..utils import PlacementNotFoundException

if TYPE_CHECKING:
    pass

MacroId: TypeAlias = UnitTypeId | UpgradeId


def compare_plans(plan_a: MacroPlan, plan_b: MacroPlan) -> int:
    if plan_a.priority < plan_b.priority:
        return -1
    elif plan_b.priority < plan_a.priority:
        return +1
    elif plan_a.plan_id < plan_b.plan_id:
        return +1
    elif plan_b.plan_id < plan_a.plan_id:
        return -1
    return 0


@dataclass
class MacroAction(Action):
    unit: Unit
    plan: MacroPlan

    @cached_property
    def ability(self) -> AbilityId:
        return MACRO_INFO.get(self.unit.type_id, {}).get(self.plan.item, {}).get("ability")

    async def execute(self, bot: AresBot) -> bool:
        if math.isinf(self.plan.eta):
            return True
        elif self.plan.eta <= 0.0:
            if self.unit.is_carrying_resource:
                return await UseAbility(self.unit, AbilityId.HARVEST_RETURN).execute(bot)
            else:
                target = self.plan.target
                if isinstance(self.plan.target, Point2) and self.plan.item != GAS_BY_RACE[bot.race]:
                    target = await bot.find_placement(self.ability, near=self.plan.target, placement_step=1)
                return await UseAbility(self.unit, self.ability, target=target).execute(bot)
        elif not self.plan.target:
            return True
        else:
            distance = await bot.client.query_pathing(self.unit, self.plan.target.position) or 0.0
            movement_eta = 1 + distance / (1.4 * self.unit.movement_speed)
            # movement_eta = 1.2 * time_to_reach(self.unit, self.plan.target.position)
            if self.unit.is_carrying_resource:
                movement_eta += 3.0
            if self.plan.eta <= movement_eta:
                if self.plan.item == UnitTypeId.EXTRACTOR:
                    return True
                elif self.unit.is_carrying_resource:
                    return await UseAbility(self.unit, AbilityId.HARVEST_RETURN).execute(bot)
                elif 1e-3 < self.unit.position.distance_to(self.plan.target.position):
                    return await Move(self.unit, self.plan.target).execute(bot)
                else:
                    return await HoldPosition(self.unit).execute(bot)

        return True


@dataclass
class MacroPlan:
    plan_id: int
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0
    max_distance: int | None = 4
    eta: float = math.inf

    def __hash__(self) -> int:
        return hash(self.plan_id)


class MacroModule(Component):
    next_plan_id: int = 0
    future_spending = Cost(0, 0, 0, 0)
    future_timeframe = 0.0
    unassigned_plans: list[MacroPlan] = list()
    assigned_plans: dict[int, MacroPlan] = dict()
    composition: dict[UnitTypeId, int] = dict()

    @property
    def all_trainers(self):
        return [self.unit_tag_dict[t] for t in self.assigned_plans.keys() if t in self.unit_tag_dict]

    def add_plan(self, item: MacroId) -> MacroPlan:
        self.next_plan_id += 1
        plan = MacroPlan(self.next_plan_id, item)
        self.unassigned_plans.append(plan)
        return plan

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self.assigned_plans.values(), self.unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return (plan for plan in self.enumerate_plans() if plan.item == item)

    def make_composition(self) -> None:
        if 200 <= self.supply_used:
            return
        composition_have = {unit: self.count(unit) for unit in self.composition}
        for unit, target in self.composition.items():
            if target < 1:
                continue
            elif target <= composition_have[unit]:
                continue
            if any(self.get_missing_requirements(unit)):
                continue
            priority = -self.count(unit, include_planned=False) / target
            if any(self.planned_by_type(unit)):
                for plan in self.planned_by_type(unit):
                    if plan.priority == math.inf:
                        continue
                    plan.priority = priority
                    break
            else:
                plan = self.add_plan(unit)
                plan.priority = priority

    def macro(self) -> Iterable[Action]:

        reserve = Cost(0, 0, 0, 0)

        plans = sorted(
            self.enumerate_plans(),
            key=cmp_to_key(compare_plans),
            # key = lambda t : t.priority,
            reverse=True,
        )

        trainers = [
            unit
            for unit in self.all_own_units
            if (
                unit.tag not in self.assigned_plans
                and (unit.is_idle or unit.orders[0].ability.exact_id not in ALL_MACRO_ABILITIES)
            )
        ]

        # for tag, plan in list(self.assigned_plans.items()):
        #     if trainer := trainer_by_tag.get(tag):
        #         if trainer.type_id == UnitTypeId.EGG:
        #             self.unassigned_plans.append(plan)
        #             del self.assigned_plans[tag]

        trainer_by_plan = {p: self.unit_tag_dict.get(t) for t, p in self.assigned_plans.items()}

        for i, plan in enumerate(plans):
            cost = self.cost.of(plan.item)

            # if any(self.get_missing_requirements(plan.item)) and plan.priority == math.inf:
            #     break
            #
            # if 1 <= i and plan.priority == math.inf:
            #     break

            if not (trainer := trainer_by_plan.get(plan)):
                if trainer := self.search_trainer(trainers, plan.item):
                    if plan in self.unassigned_plans:
                        self.unassigned_plans.remove(plan)
                    self.assigned_plans[trainer.tag] = plan
                    trainers.remove(trainer)
                else:
                    # reserve += cost
                    # if (tf := UNIT_TRAINED_FROM.get(plan.item)) and UnitTypeId.LARVA in tf:
                    continue

            if any(self.get_missing_requirements(plan.item)):
                continue

            # if type(plan.item) == UnitTypeId:
            #     cost = self.ai.techtree.units[plan.item].cost
            # elif type(plan.item) == UpgradeId:
            #     cost = self.ai.techtree.upgrades[plan.item].cost2
            # else:
            #     raise TypeError()

            ability = MACRO_INFO.get(trainer.type_id, {}).get(plan.item, {}).get("ability")
            if ability is None:
                del self.assigned_plans[trainer.tag]
                self.unassigned_plans.append(plan)
                continue

            if not (trainer and ability and trainer.is_using_ability(ability)):
                reserve += cost

            if plan.target is None:
                try:
                    plan.target = self.get_target(trainer, plan)
                except PlacementNotFoundException:
                    continue

            if any(self.get_missing_requirements(plan.item)):
                plan.eta = math.inf
                continue

            eta = 0.0
            if 0 < cost.minerals:
                eta = max(
                    eta,
                    60 * (reserve.minerals - self.minerals) / max(1, self.income.minerals),
                )
            if 0 < cost.vespene:
                eta = max(eta, 60 * (reserve.vespene - self.vespene) / max(1, self.income.vespene))
            if 0 < cost.larva:
                eta = max(eta, 60 * (reserve.larva - self.larva.amount) / max(1, self.income.larva))
            if 0 < cost.supply:
                if self.supply_left < cost.supply:
                    eta = math.inf
            plan.eta = eta

            yield MacroAction(trainer, plan)

        cost_zero = Cost(0, 0, 0, 0)
        future_spending = cost_zero
        future_spending += sum((self.cost.of(plan.item) for plan in self.unassigned_plans), cost_zero)
        future_spending += sum(
            (self.cost.of(plan.item) for plan in self.assigned_plans.values()),
            cost_zero,
        )
        future_spending += sum(
            (self.cost.of(unit) * max(0, count - self.count(unit)) for unit, count in self.composition.items()),
            cost_zero,
        )
        self.future_spending = future_spending

        future_timeframe = 3 / 60
        if 0 < future_spending.minerals:
            future_timeframe = max(future_timeframe, future_spending.minerals / max(1, self.income.minerals))
        if 0 < future_spending.vespene:
            future_timeframe = max(future_timeframe, future_spending.vespene / max(1, self.income.vespene))
        if 0 < future_spending.larva:
            future_timeframe = max(future_timeframe, future_spending.larva / max(1, self.income.larva))
        self.future_timeframe = future_timeframe

    def get_target(self, trainer: Unit, objective: MacroPlan) -> Unit | Point2 | None:
        gas_type = GAS_BY_RACE[self.race]
        if objective.item == gas_type:
            exclude_positions = {geyser.position for geyser in self.gas_buildings}
            exclude_tags = {
                order.target
                for unit in self.workers
                for order in unit.orders
                if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
            }
            exclude_tags.update(
                {step.target.tag for step in self.planned_by_type(gas_type) if isinstance(step.target, Unit)}
            )
            geysers = [
                geyser
                for geyser in self.get_owned_geysers()
                if (geyser.position not in exclude_positions and geyser.tag not in exclude_tags)
            ]
            if not any(geysers):
                raise PlacementNotFoundException()
            else:
                return random.choice(geysers)

        if not (entry := MACRO_INFO.get(trainer.type_id)):
            return None
        if not (data := entry.get(objective.item)):
            return None
        # data = MACRO_INFO[trainer.unit.type_id][objective.item]

        if "requires_placement_position" in data:
            position = self.get_target_position(objective.item)
            objective in {UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}

            # if objective.max_distance is not None:
            #     max_distance = objective.max_distance
            #     position = await self.find_placement(
            #         trainer.macro_ability,
            #         position,
            #         max_distance=max_distance,
            #         placement_step=1,
            #         addon_place=with_addon,
            #     )
            if position is None:
                raise PlacementNotFoundException()
            else:
                return position
        else:
            return None

    def search_trainer(self, trainers: Units, item: MacroId) -> Unit | None:
        trainer_types = ITEM_TRAINED_FROM_WITH_EQUIVALENTS[item]

        trainers_filtered = (
            trainer
            for trainer in trainers
            if (
                trainer.type_id in trainer_types
                and trainer.is_ready
                and (trainer.is_idle or not trainer.is_structure)
                and trainer.tag not in self.assigned_plans
            )
        )

        # return next(trainers_filtered, None)

        return min(trainers_filtered, key=lambda t: t.tag, default=None)

    def get_target_position(self, target: UnitTypeId) -> Point2:
        data = self.game_data.units[target.value]
        if target in race_townhalls[self.race]:
            for base in self.resource_manager.bases:
                if base.townhall:
                    continue
                if base.position in self.scout.blocked_positions:
                    continue
                if not base.remaining:
                    continue
                return base.position
            raise PlacementNotFoundException()

        bases = list(self.resource_manager.bases)
        random.shuffle(bases)
        for base in bases:
            if not base.townhall:
                continue
            elif not base.townhall.unit.is_ready:
                continue
            position = base.position.towards_with_random_angle(base.mineral_patches.position, 10)
            offset = data.footprint_radius % 1
            position = position.rounded.offset((offset, offset))
            return position
        raise PlacementNotFoundException()

    def make_tech(self):
        upgrades = [
            u for unit in self.composition for u in self.upgrades_by_unit(unit) if self.strategy.filter_upgrade(u)
        ]
        upgrades.append(UpgradeId.ZERGLINGMOVEMENTSPEED)
        targets: set[MacroId] = set(upgrades)
        targets.update(self.composition.keys())
        targets.update(r for item in set(targets) for r in REQUIREMENTS[item])
        for target in targets:
            if equivalents := WITH_TECH_EQUIVALENTS.get(target):
                target_met = any(self.count(t) for t in equivalents)
            else:
                target_met = bool(self.count(target))
            if not target_met:
                plan = self.add_plan(target)
                plan.priority = -1 / 3

    def upgrades_by_unit(self, unit: UnitTypeId) -> Iterable[UpgradeId]:
        if unit == UnitTypeId.ZERGLING:
            return chain(
                (UpgradeId.ZERGLINGMOVEMENTSPEED,),
                # (UpgradeId.ZERGLINGMOVEMENTSPEED, UpgradeId.ZERGLINGATTACKSPEED),
                # self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                # self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ULTRALISK:
            return chain(
                (UpgradeId.CHITINOUSPLATING, UpgradeId.ANABOLICSYNTHESIS),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BANELING:
            return chain(
                (UpgradeId.CENTRIFICALHOOKS,),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.ROACH:
            return chain(
                (UpgradeId.GLIALRECONSTITUTION, UpgradeId.BURROW, UpgradeId.TUNNELINGCLAWS),
                # (UpgradeId.GLIALRECONSTITUTION,),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.HYDRALISK:
            return chain(
                (UpgradeId.EVOLVEGROOVEDSPINES, UpgradeId.EVOLVEMUSCULARAUGMENTS),
                self.upgrade_sequence(ZERG_RANGED_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.QUEEN:
            return chain(
                # self.upgradeSequence(ZERG_RANGED_UPGRADES),
                # self.upgradeSequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.MUTALISK:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.CORRUPTOR:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_UPGRADES),
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.BROODLORD:
            return chain(
                self.upgrade_sequence(ZERG_FLYER_ARMOR_UPGRADES),
                self.upgrade_sequence(ZERG_MELEE_UPGRADES),
                self.upgrade_sequence(ZERG_ARMOR_UPGRADES),
            )
        elif unit == UnitTypeId.OVERSEER:
            return (UpgradeId.OVERLORDSPEED,)
        else:
            return []

    def upgrade_sequence(self, upgrades) -> Iterable[UpgradeId]:
        for upgrade in upgrades:
            if not self.count(upgrade, include_planned=False):
                return (upgrade,)
        return ()
