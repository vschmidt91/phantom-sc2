import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import scipy as sp
from ares.consts import GAS_BUILDINGS
from loguru import logger
from sc2.unit import Unit
from sc2.units import Units
from scipy.optimize import linprog
from sklearn.metrics import pairwise_distances

from phantom.common.action import Action, Smart
from phantom.common.assignment import Assignment
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

        # limit harvesters per resource
        # A_ub = np.tile(np.identity(len(resources)), (1, len(harvesters)))
        A_ub = sp.sparse.hstack([sp.sparse.identity(len(resources))] * len(harvesters))
        b_ub = np.full(len(resources), 2.0)

        # enforce assignment per harvester
        A_eq1 = np.repeat(np.identity(len(harvesters)), len(resources), axis=1)
        b_eq1 = np.full(len(harvesters), 1.0)

        # enforce gas target
        is_gas_building = np.array([1.0 if r.type_id in GAS_BUILDINGS else 0.0 for r in resources])
        A_eq2 = np.tile(is_gas_building, len(harvesters)).reshape((1, -1))
        b_eq2 = np.array([gas_target])

        A_eq = np.concatenate((A_eq1, A_eq2), axis=0)
        b_eq = np.concatenate((b_eq1, b_eq2), axis=0)

        harvester_to_resource = pairwise_distances(
            [h.position for h in harvesters],
            [self.observation.observation.speedmining_positions.get(r.position, r.position) for r in resources],
        )
        # harvester_to_return_point = pairwise_distances(
        #     [h.position for h in harvesters],
        #     [self.observation.observation.return_point[r.position] for r in resources],
        # )

        return_distance = np.array([self.observation.observation.return_distances[r.position] for r in resources])
        return_distance = np.repeat(return_distance[None, ...], len(harvesters), axis=0)

        # cost = (harvester_to_resource + harvester_to_return_point + 7 * return_distance).flatten()
        cost = (harvester_to_resource + return_distance).flatten()

        res = linprog(
            c=cost,
            A_ub=sp.sparse.csr_matrix(A_ub),
            b_ub=b_ub,
            A_eq=sp.sparse.csr_matrix(A_eq),
            b_eq=b_eq,
            method="interior-point",
            # options=dict(sparse=True),
            options=dict(maxiter=100, sparse=True, disp=False, tol=1e-3),
            # method="interior-point",
            # options=LINPROG_OPTIONS,
        )

        if res.x is None:
            logger.error(f"Target assigment failed: {res.message}")
            return Assignment({})

        x_opt = res.x.reshape(harvester_to_resource.shape)
        indices = x_opt.argmax(axis=1)
        a = Assignment({h: resources[idx] for (i, h), idx in zip(enumerate(harvesters), indices) if 0 < x_opt[i, idx]})

        return HarvesterAssignment({h.tag: r.position for h, r in a.items()})

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
