
from typing import Optional
import numpy as np

from s2clientprotocol.data_pb2 import AbilityData
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId

class Pool12AllIn(BotAI):

    def __init__(self, game_step: Optional[int] = None):
        self.game_step: Optional[int] = game_step
        super().__init__()

    async def on_before_start(self):
        if self.game_step:
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
        return await super().on_start()

    async def on_step(self, iteration: int):

        if not self.townhalls:
            await self.client.chat_send('gg', False)
            await self.client.debug_leave()

        pool = next(
            (p
            for p in self.structures.of_type(UnitTypeId.SPAWNINGPOOL)
            if p.is_ready),
            None)

        hatches = self.townhalls.ready.sorted_by_distance_to(self.start_location)
        queens = self.units.of_type(UnitTypeId.QUEEN).sorted_by_distance_to(self.start_location)

        if self.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED):
            gas_target = 0
        elif 96 <= self.vespene:
            gas_target = 0
        else:
            gas_target = 3

        tech_position = self.townhalls[0].position.towards(self.game_info.map_center, 5.5)
        enemy_position = self.enemy_start_locations[0]

        base_from = next((h for h in self.townhalls.ready if 0 < h.surplus_harvesters), None)
        if base_from:
            base_to = min(self.townhalls.ready, key=lambda h:h.surplus_harvesters)
            if base_to.surplus_harvesters < 0:
                worker = next((w for w in self.workers if w.order_target == base_from.tag), None)
                if worker:
                    patch = self.mineral_field.closest_to(base_to)
                    worker.gather(patch)

        for gas in self.gas_buildings.ready:
            if gas.assigned_harvesters < gas_target:
                workers = self.workers.sorted_by_distance_to(gas)
                worker = next((w for w in workers if w.is_gathering and w.order_target != gas.tag), None)
                if worker:
                    worker.gather(gas)
            elif gas_target < gas.assigned_harvesters:
                worker = next((w for w in self.workers if w.order_target == gas.tag), None)
                if worker:
                    worker.stop()

        for queen, hatch in zip(queens, hatches):
            if queen.energy < 25:
                continue
            queen(AbilityId.EFFECT_INJECTLARVA, hatch)

        for unit in self.units:
            if unit.type_id is not UnitTypeId.ZERGLING:
                continue
            if not unit.is_idle:
                continue
            if self.enemy_structures:
                unit.attack(self.enemy_structures.random.position)
            elif 10 < unit.distance_to(enemy_position):
                unit.attack(enemy_position)
            else:
                a = self.game_info.playable_area
                target = np.random.uniform((a.x, a.y), (a.right, a.top))
                target = Point2(target)
                if self.in_pathing_grid(target):
                    unit.attack(target)

        for worker in self.workers.idle:
            patch = self.mineral_field.closest_to(worker)
            worker.gather(patch)

        if (
            125 <= self.minerals
            and not self.structures.of_type(UnitTypeId.EXTRACTOR)
            and not self.already_pending(UnitTypeId.EXTRACTOR)
        ):
            geyser = self.vespene_geyser.closest_to(self.start_location)
            drone = self.workers.first
            drone.build_gas(geyser)
            return

        if (
            not pool
            and not self.already_pending(UnitTypeId.SPAWNINGPOOL)
        ):
            await self.build(UnitTypeId.SPAWNINGPOOL, near=tech_position)
            return

        if self.supply_used < 13:
            self.train(UnitTypeId.DRONE)
            return

        if (
            self.supply_cap == 14
            and not self.already_pending(UnitTypeId.OVERLORD)
        ):
            self.train(UnitTypeId.OVERLORD)
            return

        if not pool:
            return

        if self.supply_used < 16:
            self.train(UnitTypeId.ZERGLING)
            return

        if not self.already_pending_upgrade(UpgradeId.ZERGLINGMOVEMENTSPEED):
            pool(AbilityId.RESEARCH_ZERGLINGMETABOLICBOOST)
            return

        if self.supply_used < 17:
            self.train(UnitTypeId.ZERGLING)
            return

        if (
            self.supply_left <= 0
            and 2 <= self.townhalls.amount
            and not self.already_pending(UnitTypeId.OVERLORD)
        ):
            self.train(UnitTypeId.OVERLORD)
            return

        if (
            not self.already_pending(UnitTypeId.DRONE)
            and self.units.of_type(UnitTypeId.DRONE).amount < 11 * self.townhalls.amount
        ):
            self.train(UnitTypeId.DRONE)
            return

        if self.units.of_type(UnitTypeId.QUEEN).amount + self.already_pending(UnitTypeId.QUEEN) < self.townhalls.ready.amount:
            self.train(UnitTypeId.QUEEN)
            return

        if 300 <= self.minerals and not self.already_pending(UnitTypeId.HATCHERY):
            await self.expand_now()

        self.train(UnitTypeId.ZERGLING)

    def drone_to(self, target: int) -> bool:
        worker_count = self.workers.amount + self.already_pending(UnitTypeId.DRONE)
        if worker_count < target:
            self.train(UnitTypeId.DRONE)
            return True
        return False