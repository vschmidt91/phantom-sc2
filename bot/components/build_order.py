from functools import cached_property

from ares.consts import ALL_STRUCTURES, UnitRole
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from ..action import Action, Build, DoNothing, Research, Train, UseAbility
from .component import Component


class BuildOrder(Component):

    def execute_build_order(self) -> Action | None:
        return (
            self.morph_drones(13)
            or self.morph_overlords_until(2)
            or self.morph_drones(16)
            or self.take_natural()
            or self.morph_drones(18)
            or self.take_gas(1)
            or self.make_tech_bo(UnitTypeId.ZERGLING)
        )

    @cached_property
    def tech_building_position(self):
        return self.start_location.towards(self.game_info.map_center, 8).rounded.offset((.5, .5))

    def morph_drones(self, target: int) -> Action | None:
        return self.build_unit(UnitTypeId.DRONE, limit=max(0, target - int(self.supply_workers)))

    def morph_overlords_until(self, target: int) -> Action | None:
        if target <= self.units(UnitTypeId.OVERLORD).amount + self.already_pending(UnitTypeId.OVERLORD):
            return None
        return self.build_unit(UnitTypeId.OVERLORD)

    def take_gas(self, target: int) -> Action | None:
        if target <= self.count(UnitTypeId.EXTRACTOR, include_planned=False):
            return None
        elif not (trainer := self.find_trainer(UnitTypeId.EXTRACTOR)):
            return None

        # exclude actual
        exclude_positions = {geyser.position for geyser in self.gas_buildings}
        # exclude pending
        exclude_tags = {
            order.target
            for unit in self.workers
            for order in unit.orders
            if order.ability.exact_id == AbilityId.ZERGBUILD_EXTRACTOR
        }
        # exclude planned
        # exclude_tags.update(
        #     {step.target.tag for step in bot.planned_by_type(gas_type) if isinstance(step.target, Unit)}
        # )
        geysers = [
            geyser
            for geyser in self.get_owned_geysers()
            if (geyser.position not in exclude_positions and geyser.tag not in exclude_tags)
        ]
        if not any(geysers):
            return None
        geyser = geysers[0]
        self.mediator.assign_role(tag=trainer.tag, role=UnitRole.PERSISTENT_BUILDER)
        return UseAbility(trainer, AbilityId.ZERGBUILD_EXTRACTOR, target=geyser)

    def take_natural(self) -> Action | None:
        if 2 <= self.townhalls.amount:
            return None
        elif not (target := self.get_next_free_expansion()):
            return None
        return self.build_unit(UnitTypeId.HATCHERY, target=target, limit=1)

    def make_tech_bo(self, unit: UnitTypeId) -> Action | None:
        build_structures: set[UnitTypeId] = set()
        if unit == UnitTypeId.ZERGLING:
            build_structures.add(UnitTypeId.SPAWNINGPOOL)
        elif unit == UnitTypeId.MUTALISK:
            build_structures.add(UnitTypeId.SPAWNINGPOOL)
            build_structures.add(UnitTypeId.LAIR)
            build_structures.add(UnitTypeId.SPIRE)

        for requirement in build_structures:
            if action := self.build_unit(
                requirement,
                target=self.tech_building_position,
                limit=1 - len(self.mediator.get_own_structures_dict[requirement]),
            ):
                return action
        return None

    def get_next_free_expansion(self) -> Point2 | None:
        taken = {th.position for th in self.townhalls}
        return next((p for p, d in self.mediator.get_own_expansions if p not in taken), None)

    def find_trainer(
        self,
        type_id: UnitTypeId | UpgradeId,
        target: Point2 | None = None,
    ) -> Unit | None:
        def filter_trainer(t: Unit) -> bool:
            # TODO: handle reactors
            if t.type_id in ALL_STRUCTURES and not t.is_idle:
                return False
            return True

        def trainer_priority(t: Unit) -> float:
            return -t.position.distance_to(target or self.start_location)

        trainer_types = (
            UNIT_TRAINED_FROM[type_id] if isinstance(type_id, UnitTypeId) else {UPGRADE_RESEARCHED_FROM[type_id]}
        )

        def trainer_pool(t: UnitTypeId) -> Units:
            if t in ALL_STRUCTURES:
                return self.mediator.get_own_structures_dict[t]
            else:
                return self.mediator.get_own_army_dict[t]

        trainers = (t for t_id in trainer_types for t in trainer_pool(t_id) if filter_trainer(t))

        return max(trainers, key=trainer_priority, default=None)

    def build_unit(self, unit: UnitTypeId, target: Point2 | None = None, limit: int | None = None) -> Action | None:
        if limit is not None and limit <= self.already_pending(unit):
            return None
        elif self.supply_left < self.calculate_supply_cost(unit):
            return DoNothing()
        elif not (trainer := self.find_trainer(unit, target=target)):
            return DoNothing()
        # elif not self.can_afford(unit):
        #     return DoNothing()
        elif self.tech_requirement_progress(unit) < 1:
            return DoNothing()
        elif TRAIN_INFO[trainer.type_id][unit].get("requires_placement_position", False):
            return Build(trainer, unit, target)
        return Train(trainer, unit)

    def research_upgrade(self, upgrade: UpgradeId) -> Action | None:
        if self.already_pending_upgrade(upgrade):
            return None
        elif not (researcher := self.find_trainer(upgrade)):
            return DoNothing()
        # elif not self.can_afford(upgrade):
        #     return DoNothing()
        return Research(researcher, upgrade)
