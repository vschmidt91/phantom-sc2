
from typing import Optional
import numpy as np

from sc2.bot_ai import BotAI
from sc2.data import AIBuild
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

class Pool12AllIn(BotAI):

    def __init__(self, game_step: int = 1):
        self.game_step: int = game_step
        self.mine_gas: bool = True
        super().__init__()

    async def on_before_start(self):
        self.client.game_step = self.game_step
        return await super().on_before_start()

    async def on_start(self):

        # worker split
        minerals = self.expansion_locations_dict[self.start_location].mineral_field.sorted_by_distance_to(self.start_location)
        assigned = set()
        for i in range(self.workers.amount):
            patch = minerals[i % minerals.amount]
            if i < minerals.amount:
                worker = self.workers.tags_not_in(assigned).closest_to(patch)
            else:
                # usually results in double stacking
                worker = self.workers.tags_not_in(assigned).furthest_to(patch)
            worker.gather(patch)
            assigned.add(worker.tag)

        return await super().on_start()

    async def on_step(self, iteration: int):

        if not self.townhalls:
            await self.client.chat_send('gg', False)
            await self.client.debug_leave()
            return

        hatches = self.townhalls.ready.sorted(key=lambda u:u.tag)
        queens = self.units.of_type(UnitTypeId.QUEEN).sorted(key=lambda u:u.tag)

        tech_position = self.townhalls.first.position.towards(self.game_info.map_center, 5.5)
        enemy_position = self.enemy_start_locations[0]

        for queen, hatch in zip(queens, hatches):
            if 5 < queen.distance_to(hatch):
                queen.move(hatch)
            if queen.energy < 25:
                continue
            queen(AbilityId.EFFECT_INJECTLARVA, hatch)

        pool: Optional[Unit] = None
        transfer_from: Optional[Unit] = None
        transfer_to: Optional[Unit] = None
        drone_morphing_count: int = 0
        overlord_morphing_count: int = 0
        drone_count: int = 0
        extractor_count: int = 0
        pool_pending: Optional[Unit] = None
        larva: Optional[Unit] = None
        drone: Optional[Unit] = None
        drone_target: int = 0
        queen_count: int = 0
        queen_morphing_count: int = 0

        for unit in self.structures:
            if unit.is_vespene_geyser:
                extractor_count += 1
                if unit.is_ready:
                    if self.mine_gas and unit.surplus_harvesters < 0:
                        workers = self.workers.sorted_by_distance_to(unit)
                        worker = next((w for w in workers if w.is_gathering and w.order_target != unit.tag), None)
                        if worker:
                            worker.gather(unit)
                    elif not self.mine_gas and 0 < unit.assigned_harvesters:
                        for worker in self.workers:
                            if worker.order_target == unit.tag:
                                worker.stop()
            elif unit.type_id is UnitTypeId.HATCHERY:
                if unit.is_ready:
                    drone_target += min(unit.ideal_harvesters, 11)
                    if unit.is_using_ability(AbilityId.TRAINQUEEN_QUEEN):
                        queen_morphing_count += 1
                    if 0 < unit.surplus_harvesters:
                        transfer_from = unit
                    elif unit.surplus_harvesters < 0:
                        transfer_to = unit
            elif unit.type_id is UnitTypeId.SPAWNINGPOOL:
                pool_pending = unit
                if unit.is_ready:
                    pool = unit
                    if unit.is_using_ability(AbilityId.RESEARCH_ZERGLINGMETABOLICBOOST):
                        self.mine_gas = False

        for unit in self.units:
            if unit.type_id is UnitTypeId.LARVA:
                larva = unit
            elif unit.type_id is UnitTypeId.EGG:
                if unit.is_using_ability(AbilityId.LARVATRAIN_DRONE):
                    drone_morphing_count += 1
                elif unit.is_using_ability(AbilityId.LARVATRAIN_OVERLORD):
                    drone_morphing_count += 1
            elif unit.type_id is UnitTypeId.DRONE:
                drone_count += 1
                drone = unit
                if unit.is_idle:
                    patch = self.mineral_field.closest_to(unit)
                    unit.gather(patch)
                elif unit.is_using_ability(AbilityId.ZERGBUILD_SPAWNINGPOOL):
                    pool_pending = unit
                elif unit.is_using_ability(AbilityId.ZERGBUILD_EXTRACTOR):
                    extractor_count = unit
            elif unit.type_id is UnitTypeId.QUEEN:
                queen_count += 1
            elif unit.type_id is UnitTypeId.ZERGLING:
                if unit.is_idle:
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

        if transfer_from and transfer_to:
            worker = next((w for w in self.workers if w.order_target == transfer_from.tag), None)
            if worker:
                patch = self.mineral_field.closest_to(transfer_to)
                worker.gather(patch)
        
        if iteration % 2 == 0:
            return

        if 96 <= self.vespene:
            self.mine_gas = False

        if (
            125 <= self.minerals
            and not extractor_count
            and drone
        ):
            geyser = self.vespene_geyser.closest_to(self.start_location)
            drone.build_gas(geyser)
            return

        if not pool and not pool_pending:
            await self.build(UnitTypeId.SPAWNINGPOOL, near=tech_position)
            return

        if self.supply_used < 13:
            if larva:
                larva.train(UnitTypeId.DRONE, can_afford_check=True)
            return

        if (
            self.supply_cap == 14
            and overlord_morphing_count < 1
        ):
            if larva:
                larva.train(UnitTypeId.OVERLORD, can_afford_check=True)
            return

        if not pool:
            return

        if self.supply_used < 16:
            if larva:
                larva.train(UnitTypeId.ZERGLING, can_afford_check=True)
            return

        if UpgradeId.ZERGLINGMOVEMENTSPEED not in self.state.upgrades and pool.is_idle:
            pool.research(UpgradeId.ZERGLINGMOVEMENTSPEED, can_afford_check=True)
            return

        if self.supply_used < 17:
            if larva:
                larva.train(UnitTypeId.ZERGLING, can_afford_check=True)
            return

        if (
            self.supply_left <= 0
            and 2 <= self.townhalls.amount
            and overlord_morphing_count < 1
        ):
            if larva:
                larva.train(UnitTypeId.OVERLORD, can_afford_check=True)
            return

        if (
            drone_morphing_count < 1
            and drone_count + drone_morphing_count < drone_target
        ):
            if larva:
                larva.train(UnitTypeId.DRONE, can_afford_check=True)
            return

        if queen_count + queen_morphing_count < self.townhalls.ready.amount:
            self.train(UnitTypeId.QUEEN)
            return

        if (
            self.can_afford(UnitTypeId.HATCHERY)
            and drone_target <= drone_count + drone_morphing_count
            and not self.already_pending(UnitTypeId.HATCHERY)
        ):
            await self.expand_now(max_distance=0)

        if larva:
            larva.train(UnitTypeId.ZERGLING, can_afford_check=True)