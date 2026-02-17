from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from ares.behaviors.macro.mining import TOWNHALL_TARGET
from cython_extensions import cy_distance_to
from sc2.position import Point2
from sc2.unit import Unit

from phantom.common.constants import MINING_RADIUS, WORKER_RADIUS
from phantom.common.point import to_point
from phantom.common.utils import Point, get_intersections, project_point_onto_line, rectangle_perimeter


@dataclass
class Expansion:
    townhall_position: Point2
    mineral_positions: Sequence[Point]
    geyser_positions: Sequence[Point]
    gather_targets: Mapping[Point, Point2]
    return_distances: Mapping[Point, float]
    mineral_center: Point
    spore_position: Point
    spine_position: Point

    @classmethod
    def from_resources(cls, townhall_position: Point2, resources: Sequence[Unit]) -> "Expansion":
        mineral_positions = list[Point]()
        geyser_positions = list[Point]()
        gather_targets = dict[Point, Point2]()
        return_distances = dict[Point, float]()
        for resource in resources:
            p = to_point(resource.position)
            if resource.is_vespene_geyser:
                geyser_positions.append(p)
                target = resource.position.towards(townhall_position, resource.radius + WORKER_RADIUS)
                return_target = townhall_position.towards(target, TOWNHALL_TARGET)
                gather_targets[p] = target
                return_distances[p] = target.distance_to(return_target)
            elif resource.is_mineral_field:
                mineral_positions.append(p)
                target = resource.position.towards(townhall_position, MINING_RADIUS)
                for patch2 in resources:
                    if not patch2.is_mineral_field:
                        continue
                    if resource.position == patch2.position:
                        continue
                    position = project_point_onto_line(target, target - townhall_position, patch2.position)
                    distance1 = resource.position.distance_to(townhall_position)
                    distance2 = patch2.position.distance_to(townhall_position)
                    if distance1 < distance2:
                        continue
                    if patch2.position.distance_to(position) >= MINING_RADIUS:
                        continue
                    intersections = list(
                        get_intersections(resource.position, MINING_RADIUS, patch2.position, MINING_RADIUS)
                    )
                    if intersections:
                        intersection1, intersection2 = intersections
                        if intersection1.distance_to(townhall_position) < intersection2.distance_to(townhall_position):
                            target = intersection1
                        else:
                            target = intersection2
                        break
                return_target = townhall_position.towards(target, TOWNHALL_TARGET)
                gather_targets[p] = target
                return_distances[p] = target.distance_to(return_target)

        mineral_center = Point2(np.mean(mineral_positions, axis=0))
        spore_candidates = list(
            rectangle_perimeter(
                start=np.subtract(townhall_position, 3).astype(int),
                end=np.add(townhall_position, 4).astype(int),
            )
        )
        spine_candidates = list(
            rectangle_perimeter(
                start=np.subtract(townhall_position, 4).astype(int),
                end=np.add(townhall_position, 5).astype(int),
            )
        )
        spore_position = min(spore_candidates, key=lambda p: cy_distance_to(p, mineral_center))
        spine_position = max(spine_candidates, key=lambda p: cy_distance_to(p, mineral_center))

        return Expansion(
            townhall_position=townhall_position,
            mineral_positions=mineral_positions,
            geyser_positions=geyser_positions,
            gather_targets=gather_targets,
            return_distances=return_distances,
            mineral_center=to_point(mineral_center),
            spore_position=spore_position,
            spine_position=spine_position,
        )
