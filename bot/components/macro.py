import math
import random
from dataclasses import dataclass
from functools import cached_property, cmp_to_key
from itertools import chain
from typing import Iterable, TypeAlias

from ares import AresBot
from loguru import logger
from sc2.data import ActionResult, race_townhalls
from sc2.game_state import ActionRawUnitCommand
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ..action import Action, UseAbility, Move, HoldPosition
from ..constants import (
    ALL_MACRO_ABILITIES,
    GAS_BY_RACE,
    ITEM_BY_ABILITY,
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
from .base import Component

MacroId: TypeAlias = UnitTypeId | UpgradeId


@dataclass
class MacroPlan:
    plan_id: int
    item: MacroId
    target: Unit | Point2 | None = None
    priority: float = 0.0
    max_distance: int | None = 4
    eta: float = math.inf
    executed: bool = False

    def __hash__(self) -> int:
        return hash(self.plan_id)


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
class PreMove(Action):
    unit: Unit
    target: Point2
    eta: float

    async def execute(self, bot: AresBot) -> bool:
        distance = await bot.client.query_pathing(self.unit, self.target) or 0.0
        movement_eta = 1 + distance / (1.4 * self.unit.movement_speed)
        if self.eta <= movement_eta:
            if 1e-3 < self.unit.distance_to(self.target):
                return self.unit.move(self.target)
            else:
                return self.unit.hold_position()
        return True


class Macro(Component):
    next_plan_id: int = 0
    future_spending = Cost(0, 0, 0, 0)
    _unassigned_plans: list[MacroPlan] = list()
    _assigned_plans: dict[int, MacroPlan] = dict()
    composition: dict[UnitTypeId, int] = dict()

    @property
    def all_trainers(self):
        return [self.unit_tag_dict[t] for t in self._assigned_plans.keys() if t in self.unit_tag_dict]

    def add_plan(self, item: MacroId) -> MacroPlan:
        self.next_plan_id += 1
        plan = MacroPlan(self.next_plan_id, item)
        self._unassigned_plans.append(plan)
        logger.info(f"Adding {plan=}")
        return plan

    def enumerate_plans(self) -> Iterable[MacroPlan]:
        return chain(self._assigned_plans.values(), self._unassigned_plans)

    def planned_by_type(self, item: MacroId) -> Iterable[MacroPlan]:
        return (plan for plan in self.enumerate_plans() if plan.item == item)

    def make_composition(self) -> None:
        if 200 <= self.supply_used:
            return
        for unit, target in self.composition.items():
            have = self.count(unit)
            if target < 1:
                continue
            elif target <= have:
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

    async def premove(self, unit: Unit, target: Point2, eta: float) -> Action | None:
        distance = await self.client.query_pathing(unit, target) or 0.0
        movement_eta = 1 + distance / (1.4 * unit.movement_speed)
        if eta <= movement_eta:
            if 1e-3 < unit.distance_to(target):
                return Move(unit, target)
            else:
                return HoldPosition(unit)
        return None

    def handle_actions(self) -> None:
        for action in self.state.actions_unit_commands:
            for tag in action.unit_tags:
                self.handle_action(action, tag)

        for error in self.state.action_errors:
            if error.result == ActionResult.CantBuildLocationInvalid.value:
                if plan := self._assigned_plans.get(error.unit_tag):
                    plan.target = None
                    logger.info(f"resetting target for {plan=}")

    def handle_action(self, action: ActionRawUnitCommand, tag: int) -> None:
        unit = self.unit_tag_dict.get(tag)
        item = ITEM_BY_ABILITY.get(action.exact_id)
        if unit and unit.type_id == UnitTypeId.EGG:
            # commands issued to a specific larva will be received by a random one
            # therefore, a direct lookup will usually be incorrect
            # instead, all plans are checked for a match
            for t, p in self._assigned_plans.items():
                if item == p.item:
                    tag = t
                    break
        if plan := self._assigned_plans.get(tag):
            if item == plan.item:
                del self._assigned_plans[tag]
                logger.info(f"Action matched plan: {action=}, {tag=}, {plan=}")

        elif action.exact_id in ALL_MACRO_ABILITIES:
            logger.info(f"Action performed by non-existing unit: {action=}, {tag=}")

    async def do_macro(self) -> list[Action]:

        actions: list[Action] = []

        reserve = Cost(0, 0, 0, 0)

        self.handle_actions()

        plans = sorted(
            self.enumerate_plans(),
            key=cmp_to_key(compare_plans),
            reverse=True,
        )

        if len(plans) != len(set(plans)):
            logger.error(f"duplicate plans: {plans=}")

        for plan in list(self._unassigned_plans):
            if trainer := self.find_trainer(self.all_own_units, plan.item):
                logger.info(f"Assigning {trainer=} for {plan=}")
                if plan in self._unassigned_plans:
                    self._unassigned_plans.remove(plan)
                self._assigned_plans[trainer.tag] = plan

        for i, (tag, plan) in enumerate(list(self._assigned_plans.items())):

            plan.eta = math.inf
            
            trainer = self.unit_tag_dict.get(tag)
            if not trainer or trainer.type_id == UnitTypeId.EGG:
                logger.info(f"resetting {trainer=} for {plan=}")
                del self._assigned_plans[tag]
                self._unassigned_plans.append(plan)
                continue

            ability = MACRO_INFO.get(trainer.type_id, {}).get(plan.item, {}).get("ability")
            if not ability:
                logger.info(f"resetting due to missing ability {trainer=} for {plan=}")
                del self._assigned_plans[tag]
                self._unassigned_plans.append(plan)
                continue

            if any(self.get_missing_requirements(plan.item)):
                continue

            # reset target on failure
            if plan.executed:
                logger.info(f"resetting target for {plan=}")
                plan.target = None
                plan.executed = False

            if not plan.target:
                try:
                    plan.target = self.get_target(trainer, plan)
                except PlacementNotFoundException:
                    continue
                    
            cost = self.cost.of(plan.item)
            reserve += cost
            plan.eta = self.get_eta(cost, reserve)

            if trainer.is_carrying_resource:
                actions.append(UseAbility(trainer, AbilityId.HARVEST_RETURN))
            elif plan.eta <= 0.0:
                plan.executed = True
                actions.append(UseAbility(trainer, ability, target=plan.target))
            elif plan.target:
                if action := await self.premove(trainer, plan.target.position, plan.eta):
                    actions.append(action)

        return actions

    def get_eta(self, cost: Cost, reserve: Cost) -> float:
        eta = 0.0
        if 0 < cost.minerals:
            eta = max(
                eta,
                60 * (reserve.minerals - self.minerals) / max(1.0, self.income.minerals),
            )
        if 0 < cost.vespene:
            eta = max(eta, 60 * (reserve.vespene - self.vespene) / max(1.0, self.income.vespene))
        if 0 < cost.larva:
            eta = max(eta, 60 * (reserve.larva - self.larva.amount) / max(1.0, self.income.larva))
        if 0 < cost.supply:
            if self.supply_left < cost.supply:
                eta = math.inf
        return eta

    @property
    def bank(self) -> Cost:
        return Cost(self.minerals, self.vespene, self.supply_left, self.larva.amount)

    @property
    def future_spending(self):
        cost_zero = Cost(0, 0, 0, 0)
        future_spending = cost_zero
        future_spending += sum((self.cost.of(plan.item) for plan in self._unassigned_plans), cost_zero)
        future_spending += sum(
            (self.cost.of(plan.item) for plan in self._assigned_plans.values()),
            cost_zero,
        )
        future_spending += sum(
            (self.cost.of(unit) * max(0, count - self.count(unit)) for unit, count in self.composition.items()),
            cost_zero,
        )
        return future_spending

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
            exclude_tags.update({p.target.tag for p in self.planned_by_type(gas_type) if isinstance(p.target, Unit)})
            geysers = [
                geyser.unit
                for geyser in self.owned_geysers
                if (geyser.position not in exclude_positions and geyser.unit.tag not in exclude_tags)
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
            if not position:
                raise PlacementNotFoundException()
            return position
        else:
            return None

    def find_trainer(self, trainers: Units, item: MacroId) -> Unit | None:
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
            trainers_filtered.sort(key=lambda t: t.tag)
            return trainers_filtered[0]

        return None

    def get_target_position(self, target: UnitTypeId) -> Point2 | None:
        data = self.game_data.units[target.value]
        if target in race_townhalls[self.race]:
            for base in self.bases:
                if base.townhall:
                    continue
                if base.position in self.blocked_positions:
                    continue
                if not base.remaining:
                    continue
                return base.position
            return None

        bases = list(self.bases)
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

    def make_tech(self) -> None:
        upgrades = [u for unit in self.composition for u in self.upgrades_by_unit(unit) if self.filter_upgrade(u)]
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
                plan.priority = -1 / 2

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
