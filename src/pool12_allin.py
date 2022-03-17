
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set
from itertools import chain

import numpy as np
import math

from sc2.bot_ai import BotAI
from sc2.ids.buff_id import BuffId
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units

SPEEDMINING_DISTANCE = 1.8

def get_intersections(p0: Point2, r0: float, p1: Point2, r1: float) -> Iterable[Point2]:
    """yield the intersection points of two circles at points p0, p1 with radii r0, r1"""
    p01 = p1 - p0
    d = np.linalg.norm(p01)
    if d == 0:
        return # intersection is empty or infinite
    if d < abs(r0 - r1):
        return # circles inside of each other
    if r0 + r1 < d:
        return # circles too far apart
    a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
    h = math.sqrt(r0 ** 2 - a ** 2)
    pm = p0 + (a / d) * p01
    po = (h / d) * np.array([p01.y, -p01.x])
    yield pm + po
    yield pm - po

class Pool12AllIn(BotAI):

    def __init__(self) -> None:
        self.pool_drone: Optional[Unit] = None
        self.tags: Set[str] = set()
        self.gas_harvesters: Set[int] = set()
        self.game_step: int = 2
        self.speedmining_enabled: bool = True
        super().__init__()

    async def on_before_start(self) -> None:
        self.client.game_step = self.game_step

    async def on_start(self) -> None:
        self.geyser = self.vespene_geyser.closest_to(self.start_location)
        self.pool_position = self.get_pool_position()
        self.speedmining_positions = self.get_speedmining_positions()
        self.split_workers()

    async def on_step(self, iteration: int) -> None:

        if not any(self.townhalls):
            # surrender
            await self.add_tag('gg')
            await self.client.chat_send('(gg)', False)
            await self.client.quit()
            return

        if self.enemy_structures.flying and not any(self.enemy_structures.not_flying):
            # high performance mode
            await self.add_tag('cleanup')
            self.client.game_step = 10 * self.game_step
            self.speedmining_enabled = False
            army_types = { UnitTypeId.ZERGLING, UnitTypeId.QUEEN, UnitTypeId.OVERLORD }
        else:
            self.client.game_step = self.game_step
            self.speedmining_enabled = self.time < 8 * 60
            army_types = { UnitTypeId.ZERGLING }

        self.transfer_from: List[Unit] = list()
        self.transfer_to: List[Unit] = list()
        self.transfer_from_gas: List[Unit] = list()
        self.transfer_to_gas: List[Unit] = list()
        self.inject_queens: List[Unit] = list()
        self.idle_hatches: List[Unit] = list()
        self.drone: Optional[Unit] = None
        self.hatch_morphing: Optional[Unit] = None
        self.pool: Optional[Unit] = None
        self.abilities: Counter[AbilityId] = Counter(o.ability.exact_id for u in self.all_own_units for o in u.orders)

        self.resource_by_tag = { unit.tag: unit for unit in chain(self.mineral_field, self.gas_buildings) }
        for structure in self.structures:
            self.micro_structure(structure)

        for worker in self.workers:
            self.micro_worker(worker)

        for unit in self.units:
            if unit.type_id in army_types:
                self.micro_army(unit)
            elif unit.type_id == UnitTypeId.QUEEN:
                self.inject_queens.append(unit)

        if UnitTypeId.QUEEN not in army_types:
            self.inject_larvae()
        self.macro()

    def macro(self) -> None:
        larva_per_second = 0
        for hatchery in self.townhalls:
            if hatchery.is_ready:
                larva_per_second += 1/11
                if hatchery.has_buff(BuffId.QUEENSPAWNLARVATIMER):
                    larva_per_second += 3/29
        minerals_for_lings = 50 * 60 * larva_per_second # maximum we can possibly spend on lings
        mineral_starved = self.minerals < 150 and self.state.score.collection_rate_minerals < 1.2 * minerals_for_lings # aim for a 20% surplus
        drone_max = sum(hatch.ideal_harvesters for hatch in self.townhalls)
        queen_missing = self.townhalls.amount - (len(self.inject_queens) + self.abilities[AbilityId.TRAINQUEEN_QUEEN])
        if not self.pool and self.abilities[AbilityId.ZERGBUILD_SPAWNINGPOOL] < 1:
            if 200 <= self.minerals and self.pool_drone:
                self.pool_drone.build(UnitTypeId.SPAWNINGPOOL, self.pool_position)
            elif 170 <= self.minerals and not self.pool_drone:
                self.pool_drone = self.drone
                self.pool_drone.move(self.pool_position)
        elif self.supply_used < 13:
            self.train(UnitTypeId.DRONE)
        elif self.gas_buildings.amount < 1 and self.abilities[AbilityId.ZERGBUILD_EXTRACTOR] < 1:
            if self.drone:
                self.drone.build_gas(self.geyser)
        elif self.supply_cap == 14 and self.abilities[AbilityId.LARVATRAIN_OVERLORD] < 1:
            self.train(UnitTypeId.OVERLORD)
        elif not self.pool.is_ready:
            pass
        elif self.larva and 1 <= self.supply_left:
            max_pending_drones = self.townhalls.amount
            if self.supply_workers < drone_max and mineral_starved and self.abilities[AbilityId.LARVATRAIN_DRONE] < max_pending_drones:
                self.train(UnitTypeId.DRONE, max_pending_drones - self.abilities[AbilityId.LARVATRAIN_DRONE])
            self.train(UnitTypeId.ZERGLING, self.larva.amount)
        elif queen_missing and 2 <= self.supply_left:
            for hatch in self.idle_hatches[:queen_missing]:
                hatch.train(UnitTypeId.QUEEN)
        elif self.pool.is_idle and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.state.upgrades:
            self.pool.research(UpgradeId.ZERGLINGMOVEMENTSPEED)
        elif self.can_afford(UnitTypeId.HATCHERY) and self.abilities[AbilityId.ZERGBUILD_HATCHERY] < 1 and not self.hatch_morphing:
            target = self.get_next_expansion()
            if self.drone and target:
                self.drone.build(UnitTypeId.HATCHERY, target)
        elif self.supply_left < self.larva.amount and self.abilities[AbilityId.LARVATRAIN_OVERLORD] < 1:
            self.train(UnitTypeId.OVERLORD)

    def micro_structure(self, unit: Unit) -> None:
        mine_gas = self.vespene < 96 and self.abilities[AbilityId.RESEARCH_ZERGLINGMETABOLICBOOST] < 1 and UpgradeId.ZERGLINGMOVEMENTSPEED not in self.state.upgrades
        if not unit.is_ready and unit.health_percentage < 0.1:
            unit(AbilityId.CANCEL)
        elif unit.is_vespene_geyser:
            if mine_gas and unit.is_ready and len(self.gas_harvesters) < 2:
                self.transfer_to_gas.extend(unit for _ in range(len(self.gas_harvesters), 2))
            elif 2 < len(self.gas_harvesters):
                self.transfer_from_gas.extend(unit for _ in range(2, len(self.gas_harvesters)))
            elif not mine_gas:
                self.transfer_from_gas.extend(unit for _ in range(0, len(self.gas_harvesters)))
        elif unit.type_id == UnitTypeId.HATCHERY:
            if unit.is_ready:
                if unit.is_idle:
                    self.idle_hatches.append(unit)
                if 0 < unit.surplus_harvesters:
                    self.transfer_from.extend(unit for _ in range(0, unit.surplus_harvesters))
                elif unit.surplus_harvesters < 0:
                    self.transfer_to.extend(unit for _ in range(unit.surplus_harvesters, 0))
            else:
                self.hatch_morphing = unit
        elif unit.type_id == UnitTypeId.SPAWNINGPOOL:
            self.pool = unit

    def micro_worker(self, unit: Unit) -> None:
        if unit.is_idle:
            if any(self.mineral_field) and (not self.pool_drone or self.pool_drone.tag != unit.tag):
                townhall = self.townhalls.closest_to(unit)
                patch = self.mineral_field.closest_to(townhall)
                unit.gather(patch)
        elif any(self.transfer_from) and any(self.transfer_to) and unit.order_target == self.transfer_from[0].tag:
            patch = self.mineral_field.closest_to(self.transfer_to.pop(0))
            self.transfer_from.pop(0)
            unit.gather(patch)
        elif any(self.transfer_from_gas) and unit.order_target == self.transfer_from_gas[0].tag:
            unit.stop()
            self.transfer_from_gas.pop(0)
            self.gas_harvesters.difference_update([unit.tag])
        elif any(self.transfer_to_gas) and unit.order_target != self.transfer_to_gas[0] and not unit.is_carrying_minerals and len(unit.orders) < 2 and unit.order_target not in self.close_minerals:
            unit.gather(self.transfer_to_gas.pop(0))
            self.gas_harvesters.add(unit.tag)
        elif not unit.is_carrying_resource and len(unit.orders) == 1 and unit.order_target not in self.close_minerals and unit.tag not in self.gas_harvesters:
            self.drone = unit
        if self.speedmining_enabled and len(unit.orders) == 1:
            target = None
            if unit.is_returning:
                target = self.townhalls.closest_to(unit)
                move_target = target.position.towards(unit.position, target.radius + unit.radius)
            elif unit.is_gathering:
                target = self.resource_by_tag.get(unit.order_target)
                if target:
                    move_target = self.speedmining_positions[target.position]
            if target and 2 * unit.radius < unit.distance_to(move_target) < SPEEDMINING_DISTANCE:
                unit.move(move_target)
                unit(AbilityId.SMART, target, True)

    def micro_army(self, unit: Unit) -> None:
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

    def inject_larvae(self):
        hatches: List[Unit] = sorted(self.townhalls, key = lambda u : u.tag)
        self.inject_queens.sort(key = lambda u : u.tag)
        for hatch, queen in zip(hatches, self.inject_queens):
            if 25 <= queen.energy and hatch.is_ready:
                queen(AbilityId.EFFECT_INJECTLARVA, hatch)
            elif not queen.is_moving:
                target = hatch.position.towards(self.game_info.map_center, hatch.radius + queen.radius)
                if 1 < queen.distance_to(target):
                    queen.move(target)

    async def add_tag(self, tag: str):
        """tags the replay"""
        if tag not in self.tags:
            await self.client.chat_send(f'Tag:{tag}@{self.time_formatted}', True)
            self.tags.add(tag)
        
    def get_next_expansion(self) -> Optional[Point2]:
        """find closest untaken expansion"""
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

    def get_speedmining_positions(self) -> Dict[Point2, Point2]:
        """fix workers bumping into adjacent minerals by slightly shifting the move commands"""
        targets = dict()
        worker_radius = self.workers[0].radius
        expansions: Dict[Point2, Units] = self.expansion_locations_dict
        for base, resources in expansions.items():
            for resource in resources:
                mining_radius = resource.radius + worker_radius
                target = resource.position.towards(base, mining_radius)
                for resource2 in resources.closer_than(mining_radius, target):
                    points = get_intersections(resource.position, mining_radius, resource2.position, resource2.radius + worker_radius)
                    target = min(points, key = lambda p : p.distance_to(self.start_location), default = target)
                targets[resource.position] = target
        return targets

    def get_pool_position(self) -> Point2:
        """find position for the spawning pool"""
        position = self.start_location.towards(self.game_info.map_center, -10)
        position.rounded.offset((.5, .5))
        return position

    def split_workers(self) -> None:
        """distribute initial workers on mineral patches"""
        minerals = self.expansion_locations_dict[self.start_location].mineral_field.sorted_by_distance_to(self.start_location)
        self.close_minerals = { m.tag for m in minerals[0:4] }
        assigned = set()
        for i in range(self.workers.amount):
            patch = minerals[i % len(minerals)]
            if i < len(minerals):
                # first, each patch gets one worker closest to it
                worker = self.workers.tags_not_in(assigned).closest_to(patch)
            else:
                # the remaining workers get longer paths
                # this usually results in double stacking without having to spam orders
                worker = self.workers.tags_not_in(assigned).furthest_to(patch)
            worker.gather(patch)
            assigned.add(worker.tag)