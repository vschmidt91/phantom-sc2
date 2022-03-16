"""
This bot attempts to stack workers 'perfectly'.
This is only a demo that works on game start, but does not work when adding more workers or bases.

This bot exists only to showcase how to keep track of mineral tag over multiple steps / frames.

Task for the user who wants to enhance this bot:
- Allow mining from vespene geysirs
- Remove dead workers and re-assign (new) workers to that mineral patch, or pick a worker from a long distance mineral patch
- Re-assign workers when new base is completed (or near complete)
- Re-assign workers when base died
- Re-assign workers when mineral patch mines out
- Re-assign workers when gas mines out
"""
from collections import defaultdict
import os
import sys
import math
import numpy as np

from sc2.ids.ability_id import AbilityId
from src.utils import dot

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from typing import Dict, List, Set, Iterable

from loguru import logger

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

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

DISTANCE = 1.5
RESULTS = defaultdict(lambda:[])

class WorkerStackBot(BotAI):
    def __init__(self):
        self.worker_to_mineral_patch_dict: Dict[int, int] = dict()

    async def on_start(self):
        self.client.game_step = 1
        self.speedmining_positions = self.get_speedmining_positions()
        self.assign_workers()

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

    def assign_workers(self):
        minerals = self.mineral_field.closer_than(10, self.start_location).sorted_by_distance_to(self.start_location)
        for i in range(len(self.workers)):
            mineral = minerals[i % len(minerals)]
            workers = self.workers.tags_not_in(self.worker_to_mineral_patch_dict)
            worker = workers.closest_to(mineral)
            self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag

    async def on_step(self, iteration: int):
        global DISTANCE
        global RESULTS
        
        minerals: Dict[int, Unit] = {mineral.tag: mineral for mineral in self.mineral_field}

        for worker in self.workers:
            if not self.townhalls:
                logger.error(f"All townhalls died - can't return resources")
                break

            worker: Unit
            mineral_tag = self.worker_to_mineral_patch_dict[worker.tag]
            mineral = minerals.get(mineral_tag, None)
            if mineral is None:
                logger.error(f"Mined out mineral with tag {mineral_tag} for worker {worker.tag}")
                continue

            townhall = self.townhalls.closest_to(worker)

            if worker.is_gathering and worker.order_target != mineral.tag:
                worker(AbilityId.SMART, mineral)
            elif worker.is_idle:
                worker(AbilityId.SMART, mineral)
            elif len(worker.orders) == 1:
                if worker.is_returning:
                    target = townhall
                    move_target = townhall.position.towards(worker.position, townhall.radius + worker.radius)
                else:
                    target = mineral
                    move_target = self.speedmining_positions[mineral.position]
                if (
                    2 * worker.radius < worker.distance_to(move_target) < DISTANCE
                ):
                    worker.move(move_target)
                    worker(AbilityId.SMART, target, True)

        if 1 * 60 * 22.4 <= self.state.game_loop:
            RESULTS[DISTANCE].append(self.state.score.collected_minerals)
            # print(self.minerals)
            await self.client.debug_leave()


def main():
    global DISTANCE
    global RESULTS
    while True:
        for d in [1.6, 1.8, 2.0]:
            DISTANCE = d
            run_game(
                maps.get("RomanticideAIE"),
                [Bot(Race.Protoss, WorkerStackBot()),
                Computer(Race.Terran, Difficulty.VeryEasy)],
                realtime=False,
                # random_seed=0,
            )
            print(RESULTS)


if __name__ == "__main__":
    main()