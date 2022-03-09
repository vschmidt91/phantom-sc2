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

from sc2.ids.ability_id import AbilityId
from src.utils import dot

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from typing import Dict, List, Set

from loguru import logger

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

MINING_RADIUS = 1.325
# MINING_RADIUS = 1.4

MINERAL_RADIUS = 1.125
HARVESTER_RADIUS = 0.375

def project_point_onto_line(p: Point2, d: Point2, x: Point2) -> float:
    n = Point2((d[1], -d[0]))
    return x - dot(x - p, n) / dot(n, n) * n

def get_intersections(p0: Point2, r0: float, p1: Point2, r1: float) -> List[Point2]:
    return _get_intersections(p0.x, p0.y, r0, p1.x, p1.y, r1)


def _get_intersections(x0: float, y0: float, r0: float, x1: float, y1: float, r1: float) -> List[Point2]:
    # circle 1: (x0, y0), radius r0
    # circle 2: (x1, y1), radius r1

    d = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)

    # non intersecting
    if d > r0 + r1:
        return []
    # One circle within other
    if d < abs(r0 - r1):
        return []
    # coincident circles
    if d == 0 and r0 == r1:
        return []
    else:
        a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
        h = math.sqrt(r0 ** 2 - a ** 2)
        x2 = x0 + a * (x1 - x0) / d
        y2 = y0 + a * (y1 - y0) / d
        x3 = x2 + h * (y1 - y0) / d
        y3 = y2 - h * (x1 - x0) / d

        x4 = x2 - h * (y1 - y0) / d
        y4 = y2 + h * (x1 - x0) / d

        return [Point2((x3, y3)), Point2((x4, y4))]


class WorkerStackBot(BotAI):
    def __init__(self):
        self.worker_to_mineral_patch_dict: Dict[int, int] = {}
        self.mineral_patch_to_list_of_workers: Dict[int, Set[int]] = {}
        self.minerals_sorted_by_distance: Units = Units([], self)
        # Distance 0.01 to 0.1 seems fine
        self.townhall_distance_threshold = 0.01
        # Distance factor between 0.95 and 1.0 seems fine
        self.townhall_distance_factor = 1
        self.commands = 0
        self.worker_state = defaultdict(lambda:0)

    async def on_start(self):
        self.client.game_step = 1
        self.fix_speedmining_positions()
        await self.assign_workers()

    def fix_speedmining_positions(self):
        self.speedmining_positions = dict()
        minerals = self.expansion_locations_dict[self.start_location].mineral_field
        for patch in minerals:
            target = patch.position.towards(self.start_location, MINING_RADIUS)
            for patch2 in minerals:
                if patch.position == patch2.position:
                    continue
                p = project_point_onto_line(target, target - self.start_location, patch2.position)
                if patch.position.distance_to(self.start_location) < p.distance_to(self.start_location):
                    continue
                if MINING_RADIUS <= patch2.position.distance_to(p):
                    continue
                points = get_intersections(patch.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                if len(points) == 2:
                    target = min(points, key=lambda p:p.distance_to(self.start_location))
                    break
            self.speedmining_positions[patch.position] = target

    async def assign_workers(self):
        self.minerals_sorted_by_distance = self.mineral_field.closer_than(10, self.start_location).sorted_by_distance_to(self.start_location)

        # Assign workers to mineral patch, start with the mineral patch closest to base
        for i, mineral in enumerate(self.minerals_sorted_by_distance):
            target = 2 if i < 4 else 1
            # Assign workers closest to the mineral patch
            workers = self.workers.tags_not_in(self.worker_to_mineral_patch_dict).sorted_by_distance_to(mineral)
            for worker in workers:
                # Assign at most 2 workers per patch
                # This dict is not really used further down the code, but useful to keep track of how many workers are assigned to this mineral patch - important for when the mineral patch mines out or a worker dies
                if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, [])) < target:
                    if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, [])) == 0:
                        self.mineral_patch_to_list_of_workers[mineral.tag] = {worker.tag}
                    else:
                        self.mineral_patch_to_list_of_workers[mineral.tag].add(worker.tag)
                    # Keep track of which mineral patch the worker is assigned to - if the mineral patch mines out, reassign the worker to another patch
                    self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                else:
                    break

    async def on_step(self, iteration: int):
        if self.worker_to_mineral_patch_dict:
            # Quick-access cache mineral tag to mineral Unit
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
                        0.75 < worker.distance_to(move_target) < 1.5
                        or (0.75 < worker.distance_to(move_target) and worker.is_returning)
                    ):
                        worker.move(move_target)
                        worker(AbilityId.SMART, target, True)

        # Print info every 30 game-seconds
        # if self.state.game_loop % (22.4 * 30) == 0:
        #     logger.info(f"{self.time_formatted} Mined a total of {int(self.state.score.collected_minerals)} minerals, {self.commands} commands")

        if 6720 <= self.state.game_loop:
            print(self.minerals)
            await self.client.debug_leave()


def main():
    run_game(
        maps.get("RomanticideAIE"),
        [Bot(Race.Protoss, WorkerStackBot()),
         Computer(Race.Terran, Difficulty.VeryEasy)],
        realtime=False,
        random_seed=0,
    )


if __name__ == "__main__":
    main()