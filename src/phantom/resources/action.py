import importlib
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


def cpg_solve(b, c, t, g, gw):

    n, m = c.shape

    log_n = max(1, math.ceil(math.log(max(n, m), 2)))
    N = 2 ** log_n

    prefix = f"harvest{log_n}"
    module_name = f"{prefix}.cpg_module"
    module = importlib.import_module(module_name)

    par = getattr(module, f"{prefix}_cpg_params")()
    upd = getattr(module, f"{prefix}_cpg_updated")()

    for p in ["w", "b", "t", "g", "gw"]:
        try:
            setattr(upd, p, True)
        except AttributeError:
            raise AttributeError(f"{p} is not a parameter.")

    par.w = list(np.pad(c, ((0, N - c.shape[0]), (0, N - c.shape[1])), constant_values=1.0).flatten(order="F"))
    par.b = list(np.pad(b, (0, N - b.shape[0])).flatten(order="F"))
    par.t = list(np.pad(t, (0, N - t.shape[0])).flatten(order="F"))
    par.gw = list(np.pad(gw, (0, N - gw.shape[0])).flatten(order="F"))
    par.g = float(g)

    # solve
    res = module.solve(upd, par)
    x = np.array(res.cpg_prim.x).reshape((N, N), order='F')[:n, :m]
    return x


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
        b = np.full(len(resources), 2.0)
        t = np.full(len(harvesters), 1.0)

        # enforce gas target
        is_gas_building = np.array([1.0 if r.type_id in GAS_BUILDINGS else 0.0 for r in resources])
        gw = is_gas_building
        g = gas_target

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
        cost = harvester_to_resource + return_distance

        x_opt = cpg_solve(b, cost, t, g, gw)
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
