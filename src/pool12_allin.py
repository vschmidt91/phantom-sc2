
from collections import defaultdict
from typing import DefaultDict, List, Optional, Set

import numpy as np

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

UNIT_BY_TRAIN_ABILITY = {
    AbilityId.ZERGBUILD_HATCHERY: UnitTypeId.HATCHERY,
    AbilityId.ZERGBUILD_EXTRACTOR: UnitTypeId.EXTRACTOR,
    AbilityId.ZERGBUILD_SPAWNINGPOOL: UnitTypeId.SPAWNINGPOOL,
    AbilityId.LARVATRAIN_DRONE: UnitTypeId.DRONE,
    AbilityId.LARVATRAIN_ZERGLING: UnitTypeId.ZERGLING,
    AbilityId.LARVATRAIN_OVERLORD: UnitTypeId.OVERLORD,
    AbilityId.TRAINQUEEN_QUEEN: UnitTypeId.QUEEN,
}

class Pool12AllIn(BotAI):

    def __init__(self):
        self.mine_gas: bool = True
        self.pool_drone: Optional[Unit] = None
        self.tags: Set[str] = set()
        self.game_step: int = 2
        super().__init__()

    async def on_before_start(self):
        self.client.game_step = self.game_step
        return await super().on_before_start()

    async def on_start(self):
        minerals = self.expansion_locations_dict[self.start_location].mineral_field.sorted_by_distance_to(self.start_location)
        assigned = set()
        for i in range(self.workers.amount):
            patch = minerals[i % minerals.amount]
            if i < minerals.amount:
                worker = self.workers.tags_not_in(assigned).closest_to(patch)
            else:
                worker = self.workers.tags_not_in(assigned).furthest_to(patch)
            worker.gather(patch)
            assigned.add(worker.tag)
        pool_near = self.start_location.towards(self.main_base_ramp.top_center, -9)
        pool_near = pool_near.rounded.offset((.5, .5))
        self.pool_position: Point2 = await self.find_placement(UnitTypeId.SPAWNINGPOOL, pool_near)

    async def on_step(self, iteration: int):

        if not self.townhalls:
            await self.client.chat_send('(gg)', False)
            await self.client.quit()
            return

        if 96 <= self.vespene:
            self.mine_gas = False
        if self.enemy_structures.flying and not self.enemy_structures.not_flying:
            await self.add_tag('cleanup')
            self.client.game_step = 10 * self.game_step
            army_types = { UnitTypeId.ZERGLING, UnitTypeId.QUEEN, UnitTypeId.OVERLORD }
        else:
            army_types = { UnitTypeId.ZERGLING }
            self.client.game_step = self.game_step

        transfer_from: List[Unit] = list()
        transfer_to: List[Unit] = list()
        transfer_from_gas: List[Unit] = list()
        transfer_to_gas: List[Unit] = list()
        hatches: List[Unit] = list()
        queens: List[Unit] = list()
        idle_hatches: List[Unit] = list()
        pool: Optional[Unit] = None
        drone: Optional[Unit] = None
        pending: DefaultDict[UnitTypeId, int] = defaultdict(lambda:0)

        for unit in self.structures:
            if not unit.is_idle:
                pending[UNIT_BY_TRAIN_ABILITY.get(unit.orders[0].ability.exact_id)] += 1
            if not unit.is_ready and unit.health_percentage < 0.1:
                unit(AbilityId.CANCEL)
            elif unit.is_vespene_geyser:
                if self.mine_gas and unit.surplus_harvesters < 0:
                    transfer_to_gas.extend(unit for _ in range(unit.surplus_harvesters, 0))
                elif not self.mine_gas and 0 < unit.assigned_harvesters:
                    transfer_from_gas.extend(unit for _ in range(0, unit.assigned_harvesters))
            elif unit.type_id is UnitTypeId.HATCHERY:
                if unit.is_ready:
                    hatches.append(unit)
                    if unit.is_idle:
                        idle_hatches.append(unit)
                    if 0 < unit.surplus_harvesters:
                        transfer_from.extend(unit for _ in range(0, unit.surplus_harvesters))
                    elif unit.surplus_harvesters < 0:
                        transfer_to.extend(unit for _ in range(unit.surplus_harvesters, 0))
            elif unit.type_id is UnitTypeId.SPAWNINGPOOL:
                pool = unit
                if unit.is_using_ability(AbilityId.RESEARCH_ZERGLINGMETABOLICBOOST):
                    self.mine_gas = False

        for unit in self.units:
            if not unit.is_idle:
                pending[UNIT_BY_TRAIN_ABILITY.get(unit.orders[0].ability.exact_id)] += 1
            if unit.type_id is UnitTypeId.DRONE:
                if unit.is_idle:
                    if self.mineral_field and (not self.pool_drone or self.pool_drone.tag != unit.tag):
                        patch = self.mineral_field.closest_to(unit)
                        unit.gather(patch)
                elif transfer_from and transfer_to and unit.order_target == transfer_from[0].tag:
                    patch = self.mineral_field.closest_to(transfer_to.pop(0))
                    transfer_from.pop(0)
                    unit.gather(patch)
                elif transfer_from_gas and unit.order_target == transfer_from_gas[0].tag:
                    unit.stop()
                    transfer_from_gas.pop(0)
                elif transfer_to_gas and unit.order_target != transfer_to_gas[0] and not unit.is_carrying_minerals:
                    unit.gather(transfer_to_gas.pop(0))
                elif not unit.is_carrying_resource:
                    drone = unit
            elif unit.type_id in army_types:
                if unit.is_idle or unit.is_using_ability(AbilityId.EFFECT_INJECTLARVA):
                    if self.enemy_structures:
                        unit.attack(self.enemy_structures.random.position)
                    elif not self.is_visible(self.enemy_start_locations[0]):
                        unit.attack(self.enemy_start_locations[0])
                    else:
                        a = self.game_info.playable_area
                        target = np.random.uniform((a.x, a.y), (a.right, a.top))
                        target = Point2(target)
                        if self.in_pathing_grid(target) and not self.is_visible(target):
                            unit.attack(target)
            elif unit.type_id is UnitTypeId.QUEEN:
                queens.append(unit)
                
        if not pool or not pool.is_ready:
            if not pool and not pending[UnitTypeId.SPAWNINGPOOL]:
                if 170 <= self.minerals:
                    if not self.pool_drone:
                        self.pool_drone = drone
                        self.pool_drone.move(self.pool_position)
                    self.pool_drone.build(UnitTypeId.SPAWNINGPOOL, self.pool_position)
            elif self.supply_used < 13:
                self.train(UnitTypeId.DRONE)
            elif not self.gas_buildings and not pending[UnitTypeId.EXTRACTOR]:
                geyser = self.vespene_geyser.closest_to(self.pool_position)
                if drone:
                    drone.build_gas(geyser)
            elif self.supply_cap == 14 and pending[UnitTypeId.OVERLORD] < 1:
                self.train(UnitTypeId.OVERLORD)
            return

        hatches.sort(key = lambda u : u.tag)
        queens.sort(key = lambda u : u.tag)
        for hatch, queen in zip(hatches, queens):
            if 25 <= queen.energy:
                queen(AbilityId.EFFECT_INJECTLARVA, hatch)
            elif not queen.is_moving and 10 < queen.distance_to(hatch):
                queen.move(hatch.position)

        larva_per_second = 1/11 * len(hatches) + 3/29 * min(len(queens), len(hatches))
        drone_max = sum(hatch.ideal_harvesters for hatch in self.townhalls)
        drone_target = min(drone_max, 1 + larva_per_second * 50 * 60/55)
        queen_target = len(hatches) if 16 <= self.supply_used else 0
        queen_missing = queen_target - (len(queens) + pending[UnitTypeId.QUEEN])

        if self.larva and 1 <= self.supply_left:
            self.train_nonzero(UnitTypeId.DRONE, min(1, drone_target - self.workers.amount) - pending[UnitTypeId.DRONE])
            self.train(UnitTypeId.ZERGLING, self.larva.amount)
        elif queen_missing and 2 <= self.supply_left:
            for hatch in idle_hatches[:queen_missing]:
                hatch.train(UnitTypeId.QUEEN)
        elif pool.is_idle and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.state.upgrades:
            pool.research(UpgradeId.ZERGLINGMOVEMENTSPEED)
        elif self.can_afford(UnitTypeId.HATCHERY) and not pending[UnitTypeId.HATCHERY] and len(hatches) == self.townhalls.amount:
            target = await self.get_next_expansion()
            if drone and target:
                drone.build(UnitTypeId.HATCHERY, target)
        elif self.supply_left <= 0 and not pending[UnitTypeId.OVERLORD] and 2 <= self.townhalls.amount:
            self.train(UnitTypeId.OVERLORD)

    def train_nonzero(self, unit: UnitTypeId, amount: int) -> int:
        if 0 < amount:
            return self.train(unit, amount)
        else:
            return 0

    async def add_tag(self, tag: str):
        if tag not in self.tags:
            await self.client.chat_send(f'Tag:{tag}@{self.time_formatted}', True)
            self.tags.add(tag)