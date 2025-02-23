import math
from dataclasses import dataclass
from functools import cached_property
from itertools import product

import numpy as np
from ares.consts import GAS_BUILDINGS
from loguru import logger
from sc2.unit import Unit
from sc2.units import Units
from scipy.optimize import linprog
from sklearn.metrics import pairwise_distances

from phantom.common.action import Action, Smart
from phantom.common.assignment import LINPROG_OPTIONS, Assignment
from phantom.resources.gather import GatherAction, ReturnResource
from phantom.resources.observation import HarvesterAssignment, ResourceObservation


@dataclass(frozen=True)
class ResourceAction:
    observation: ResourceObservation

    @cached_property
    def harvester_assignment(self) -> HarvesterAssignment:
        if not self.observation.mineral_fields:
            return HarvesterAssignment({})

        harvesters = self.observation.harvesters
        resources = list(self.observation.mineral_fields + self.observation.gas_buildings)

        mineral_max = sum(self.observation.harvester_target_at(p) for p in self.observation.mineral_field_at)

        gas_max = sum(self.observation.harvester_target_at(p) for p in self.observation.gas_building_at)

        if self.observation.observation.researched_speed:
            gas_target = self.gas_target
        elif self.observation.observation.bank.vespene < 100:
            gas_target = gas_max
        else:
            gas_target = 0
        gas_target = max(0, min(gas_target - self.observation.observation.workers_in_geysers, gas_max))

        harvester_max = mineral_max + gas_target
        if harvester_max < len(harvesters):
            harvesters = sorted(harvesters, key=lambda u: u.tag)[:harvester_max]

        if not any(harvesters):
            return Assignment({})
        if not any(resources):
            return Assignment({})

        pairs = list(product(harvesters, resources))

        # limit harvesters per resource
        A_ub1 = np.tile(np.eye(len(resources), len(resources)), (1, len(harvesters)))
        # b_ub1 = np.array([2.0 if r.is_mineral_field else 3.0 for r in resources])
        b_ub1 = np.full(len(resources), 2.0)

        # limit assignment per harvester
        A_ub2 = np.repeat(np.eye(len(harvesters), len(harvesters)), len(resources), axis=1)
        b_ub2 = np.full(len(harvesters), 1.0)

        A_ub = np.concatenate((A_ub1, A_ub2), axis=0)
        b_ub = np.concatenate((b_ub1, b_ub2), axis=0)

        # enforce gas target
        is_gas_building = np.array([1.0 if r.type_id in GAS_BUILDINGS else 0.0 for r in resources])
        A_eq = np.tile(is_gas_building, len(harvesters)).reshape((1, -1))
        # A_eq1 = np.repeat(is_gas_building[None, ...], len(harvesters), axis=0).flatten()
        # A_eq = np.array([A_eq1])
        b_eq = np.array([gas_target])

        harvester_to_resource = pairwise_distances(
            [h.position for h in harvesters],
            [r.position for r in resources],
        )

        return_distance = np.array([self.observation.observation.return_distances[r.position] for r in resources])
        return_distance = np.repeat(return_distance[None, ...], len(harvesters), axis=0)

        reward = (
            np.array([1.1 if h.order_target == r.tag else 1.0 for h, r in pairs])
            / (1e-8 + harvester_to_resource + 3 * return_distance).flatten()
        )

        res = linprog(
            c=-reward,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            method="highs",
            options=LINPROG_OPTIONS,
        )

        if res.x is None:
            logger.error(f"Target assigment failed: {res.message}")
            return Assignment({})

        x_opt = res.x.reshape(harvester_to_resource.shape)
        indices = x_opt.argmax(axis=1)
        assignment = HarvesterAssignment(
            {h.tag: resources[idx].position for (i, h), idx in zip(enumerate(harvesters), indices) if 0 < x_opt[i, idx]}
        )
        # assignment = Assignment({h.tag: r.position for (h, r), w in zip(pairs, opt.x) if w > 0.5})

        return assignment

    @cached_property
    def gas_target(self) -> int:
        return math.ceil(self.observation.harvesters.amount * self.observation.gas_ratio)

    def gather_with(self, unit: Unit, return_targets: Units) -> Action | None:
        if not (target_pos := self.harvester_assignment.get(unit.tag)):
            # logger.error(f"Unassinged harvester {unit}")
            return None
        if not (target := self.observation.resource_at.get(target_pos)):
            logger.error(f"No resource found at {target_pos}")
            return None
        if target.is_vespene_geyser:
            if not (target := self.observation.gas_building_at.get(target_pos)):
                logger.error(f"No gas building found at {target_pos}")
                return None
        if unit.is_idle:
            return Smart(unit, target)
        elif 2 <= len(unit.orders):
            return None
        elif unit.is_gathering:
            return GatherAction(unit, target, self.observation.observation.speedmining_positions.get(target_pos))
        elif unit.is_returning:
            assert any(return_targets)
            return_target = min(return_targets, key=lambda th: th.distance_to(unit))
            return ReturnResource(unit, return_target)
        return Smart(unit, target)
