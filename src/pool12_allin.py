
from collections import Counter, defaultdict
from typing import DefaultDict, Dict, Iterable, List, Optional, Set

import numpy as np
import math
import itertools

from sc2.bot_ai import BotAI
from sc2.ids.buff_id import BuffId
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

MINING_RADIUS = 1.325

def get_intersections(p0: Point2, r0: float, p1: Point2, r1: float) -> Iterable[Point2]:
    p01 = p1 - p0
    d = np.linalg.norm(p01)
    if 0 < d and abs(r0 - r1) <= d <= r0 + r1:
        a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
        h = math.sqrt(r0 ** 2 - a ** 2)
        q = p0 + (a / d) * p01
        o = np.array([p01.y, -p01.x])
        yield q + (h / d) * o
        yield q - (h / d) * o

class Pool12AllIn(BotAI):

    def __init__(self):
        self.pool_drone: Optional[Unit] = None
        self.geyser: Optional[Unit] = None
        self.tags: Set[str] = set()
        self.close_patches: Set[int] = set()
        self.game_step: int = 2
        self.speedmining_enabled: bool = True
        self.speedmining_positions: Dict[Point2, Point2] = dict()
        super().__init__()

    def fix_speedmining_positions(self):
        self.speedmining_positions = dict()
        for base, resources in self.expansion_locations_dict.items():
            for patch in resources.mineral_field:
                target = patch.position.towards(base, MINING_RADIUS)
                for patch2 in resources.mineral_field.closer_than(MINING_RADIUS, target):
                    points = get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                    target = min(points, key = lambda p : p.distance_to(self.start_location), default = target)
                self.speedmining_positions[patch.position] = target

    async def on_before_start(self):
        self.client.game_step = self.game_step
        return await super().on_before_start()

    async def on_start(self):
        self.geyser = self.vespene_geyser.closest_to(self.start_location)
        minerals = self.expansion_locations_dict[self.start_location].mineral_field.sorted_by_distance_to(self.start_location)
        self.close_patches = { m.tag for m in minerals[0:4] }
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
        self.fix_speedmining_positions()

    async def on_step(self, iteration: int):

        if not self.townhalls:
            await self.client.chat_send('(gg)', False)
            await self.client.quit()
            return

        if self.enemy_structures.flying and not self.enemy_structures.not_flying:
            await self.add_tag('cleanup')
            self.client.game_step = 10 * self.game_step
            self.speedmining_enabled = False
            army_types = { UnitTypeId.ZERGLING, UnitTypeId.QUEEN, UnitTypeId.OVERLORD }
        else:
            army_types = { UnitTypeId.ZERGLING }
            self.client.game_step = self.game_step
            self.speedmining_enabled = self.time < 8 * 60

        transfer_from: List[Unit] = list()
        transfer_to: List[Unit] = list()
        transfer_from_gas: List[Unit] = list()
        transfer_to_gas: List[Unit] = list()
        queens: List[Unit] = list()
        idle_hatches: List[Unit] = list()
        pool: Optional[Unit] = None
        drone: Optional[Unit] = None
        hatch_morphing: Optional[Unit] = None
        larva_per_second = 0
        abilities: Counter[AbilityId] = Counter(o.ability.exact_id for u in self.all_own_units for o in u.orders)
        mine_gas = self.vespene < 96 and not abilities[AbilityId.RESEARCH_ZERGLINGMETABOLICBOOST] and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.state.upgrades

        for unit in self.structures:
            if not unit.is_ready and unit.health_percentage < 0.1:
                unit(AbilityId.CANCEL)
            elif unit.is_vespene_geyser:
                if mine_gas and unit.is_ready and unit.assigned_harvesters < 1:
                    transfer_to_gas.extend(unit for _ in range(unit.assigned_harvesters, 1))
                elif not mine_gas and 0 < unit.assigned_harvesters:
                    transfer_from_gas.extend(unit for _ in range(0, unit.assigned_harvesters))
            elif unit.type_id == UnitTypeId.HATCHERY:
                if unit.is_ready:
                    larva_per_second += 1/11
                    if unit.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                        larva_per_second += 3/29
                    if unit.is_idle:
                        idle_hatches.append(unit)
                    if 0 < unit.surplus_harvesters:
                        transfer_from.extend(unit for _ in range(0, unit.surplus_harvesters))
                    elif unit.surplus_harvesters < 0:
                        transfer_to.extend(unit for _ in range(unit.surplus_harvesters, 0))
                else:
                    hatch_morphing = unit
            elif unit.type_id == UnitTypeId.SPAWNINGPOOL:
                pool = unit

        for unit in self.units:
            if unit.type_id == UnitTypeId.DRONE:
                if unit.is_idle:
                    if self.mineral_field and (not self.pool_drone or self.pool_drone.tag != unit.tag):
                        townhall = self.townhalls.closest_to(unit)
                        patch = self.mineral_field.closest_to(townhall)
                        unit.gather(patch)
                elif transfer_from and transfer_to and unit.order_target == transfer_from[0].tag:
                    patch = self.mineral_field.closest_to(transfer_to.pop(0))
                    transfer_from.pop(0)
                    unit.gather(patch)
                elif transfer_from_gas and unit.order_target == transfer_from_gas[0].tag:
                    unit.stop()
                    transfer_from_gas.pop(0)
                elif transfer_to_gas and unit.order_target != transfer_to_gas[0] and not unit.is_carrying_minerals and len(unit.orders) < 2 and unit.order_target not in self.close_patches:
                    unit.gather(transfer_to_gas.pop(0))
                elif not unit.is_carrying_resource and len(unit.orders) < 2 and unit.order_target not in self.close_patches:
                    drone = unit

                if self.speedmining_enabled and len(unit.orders) == 1:
                    if unit.is_returning and unit.is_carrying_minerals:
                        target = self.townhalls.closest_to(unit)
                        move_target = target.position.towards(unit.position, target.radius + unit.radius)
                    elif unit.is_gathering:
                        target = self.mineral_field.find_by_tag(unit.order_target) or self.gas_buildings.find_by_tag(unit.order_target)
                        if target:
                            move_target = self.speedmining_positions.get(target.position)
                            if not move_target:
                                move_target = target.position.towards(unit.position, target.radius + unit.radius)
                    else:
                        target = None
                    if target and 0.75 < unit.distance_to(move_target) < 2:
                        unit.move(move_target)
                        unit(AbilityId.SMART, target, True)

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
            elif unit.type_id == UnitTypeId.QUEEN:
                queens.append(unit)

        hatches = sorted(self.townhalls, key = lambda u : u.tag)
        queens.sort(key = lambda u : u.tag)
        for hatch, queen in zip(hatches, queens):
            if 25 <= queen.energy and hatch.is_ready:
                queen(AbilityId.EFFECT_INJECTLARVA, hatch)
            elif not queen.is_moving:
                target = hatch.position.towards(self.game_info.map_center, hatch.radius + queen.radius)
                if 1 < queen.distance_to(target):
                    queen.move(target)

        mineral_starved = self.minerals < 150 and self.state.score.collection_rate_minerals < 1.2 * 50 * 60 * larva_per_second
        drone_max = sum(hatch.ideal_harvesters for hatch in self.townhalls)
        queen_missing = self.townhalls.amount - (len(queens) + abilities[AbilityId.TRAINQUEEN_QUEEN])
                
        if not pool and not abilities[AbilityId.ZERGBUILD_SPAWNINGPOOL]:
            if 200 <= self.minerals and self.pool_drone:
                self.pool_drone.build(UnitTypeId.SPAWNINGPOOL, self.pool_position)
            elif 170 <= self.minerals and not self.pool_drone:
                self.pool_drone = drone
                self.pool_drone.move(self.pool_position)
        elif self.supply_used < 12:
            self.train(UnitTypeId.DRONE)
        elif not self.gas_buildings.amount and not abilities[AbilityId.ZERGBUILD_EXTRACTOR]:
            if drone:
                drone.build_gas(self.geyser)
        elif self.supply_used < 13:
            self.train(UnitTypeId.DRONE)
        elif self.supply_cap == 14 and not abilities[AbilityId.LARVATRAIN_OVERLORD]:
            self.train(UnitTypeId.OVERLORD)
        elif not pool.is_ready:
            pass
        elif self.larva and 1 <= self.supply_left:
            if self.supply_workers < drone_max and mineral_starved and not abilities[AbilityId.LARVATRAIN_DRONE]:
                self.train(UnitTypeId.DRONE)
            self.train(UnitTypeId.ZERGLING, self.larva.amount)
        elif queen_missing and 2 <= self.supply_left:
            for hatch in idle_hatches[:queen_missing]:
                hatch.train(UnitTypeId.QUEEN)
        elif pool.is_idle and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.state.upgrades:
            pool.research(UpgradeId.ZERGLINGMOVEMENTSPEED)
        elif self.can_afford(UnitTypeId.HATCHERY) and not abilities[AbilityId.ZERGBUILD_HATCHERY] and not hatch_morphing:
            target = self.get_next_expansion()
            if drone and target:
                drone.build(UnitTypeId.HATCHERY, target)
        elif self.supply_left <= 0 and not abilities[AbilityId.LARVATRAIN_OVERLORD] and 2 <= self.townhalls.amount:
            self.train(UnitTypeId.OVERLORD)

    async def add_tag(self, tag: str):
        if tag not in self.tags:
            await self.client.chat_send(f'Tag:{tag}@{self.time_formatted}', True)
            self.tags.add(tag)
        
    def get_next_expansion(self) -> Optional[Point2]:
        townhall_positions = { townhall.position for townhall in self.townhalls }
        def distance(b: Point2) -> float:
            d = 0.0
            d += b.distance_to(self.start_location)
            d += b.distance_to(self.main_base_ramp.bottom_center)
            return d
        base = min(
            (b for b in self.expansion_locations_list if b not in townhall_positions),
            key = distance,
            default = None
        )
        return base