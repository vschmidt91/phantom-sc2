
from s2clientprotocol.error_pb2 import HarvestersNotRequired
from s2clientprotocol.sc2api_pb2 import Observation
from sc2.position import Point2
from typing import Dict, Iterable, Set, List, Optional
from itertools import chain

from sc2.unit import Unit
from sc2.units import Units
from suntzu import minerals
from suntzu.minerals import Minerals
from suntzu.gas import Gas

class Base(object):

    def __init__(self,
        townhall_position: Point2,
        minerals: Iterable[Minerals],
        gasses: Iterable[Gas],
    ):
        self.townhall_position: Point2 = townhall_position
        self.minerals: List[Minerals] = sorted(
            minerals,
            key = lambda m : m.position.distance_to(townhall_position)
        )
        self.gasses: List[Gas] = sorted(
            gasses,
            key = lambda g : g.position.distance_to(townhall_position)
        )
        self.mineral_harvesters_max: int = 0
        self.townhall: Optional[int] = None

    def add_mineral_harvester(self, harvester: int):
        mineral = next((
            m for m in self.minerals
            if m.harvester_balance < 0
        ), None)
        if not mineral:
            mineral = min(self.minerals, key=lambda m : m.harvester_balance)
        mineral.harvesters.add(harvester)

    def request_mineral_harvester(self) -> Optional[int]:
        mineral = next((
            m
            for m in self.minerals
            if 0 <= m.harvester_balance
        ), None)
        if not mineral:
            mineral = next((
                m
                for m in self.minerals[::-1]
                if any(m.harvesters)
            ), None)
        if not mineral:
            return None
        harvester = next(iter(mineral.harvesters), None)
        if harvester:
            mineral.harvesters.remove(harvester)
        return harvester

    def add_gas_harvester(self, harvester: int):
        gas = min(self.gasses, key=lambda g : g.harvester_balance)
        gas.harvesters.add(harvester)

    def request_gas_harvester(self) -> Optional[int]:
        gas = max((
            g for g in self.gasses
            if any(g.harvesters)),
            key=lambda g : g.harvester_balance,
            default=None
        )
        if not gas:
            return None
        harvester = next(iter(gas.harvesters), None)
        if harvester:
            gas.harvesters.remove(harvester)
        return harvester

    def add_harvester(self, harvester: int) -> Optional[int]:
        if self.mineral_harvester_balance < self.gas_harvester_balance:
            return self.add_mineral_harvester(harvester)
        else:
            return self.add_gas_harvester(harvester)

    def request_harvester(self) -> Optional[int]:
        if self.gas_harvester_balance <= self.mineral_harvester_balance:
            return self.request_mineral_harvester() or self.request_gas_harvester()
        else:
            return self.request_gas_harvester() or self.request_mineral_harvester()

    def remove_harvester(self, harvester: int):
        for resource in chain(self.minerals, self.gasses):
            if harvester in resource.harvesters:
                resource.harvesters.remove(harvester)

    @property
    def mineral_harvester_count(self) -> int:
        return sum(len(m.harvesters) for m in self.minerals)

    @property
    def mineral_harvester_target(self) -> int:
        return sum(m.harvester_target for m in self.minerals)

    @property
    def mineral_harvester_balance(self) -> int:
        return sum(m.harvester_balance for m in self.minerals)

    @property
    def gas_harvester_count(self) -> int:
        return sum(len(g.harvesters) for g in self.gasses)

    @property
    def gas_harvester_target(self) -> int:
        return sum(g.harvester_target for g in self.gasses)

    @property
    def gas_harvester_balance(self) -> int:
        return sum(g.harvester_balance for g in self.gasses)

    @property
    def harvester_balance(self) -> int:
        return self.mineral_harvester_balance + self.gas_harvester_balance

    def update(self, observation: Observation):
        
        for mineral in self.minerals:
            mineral.update(observation)

        for gas in self.gasses:
            gas.update(observation)

        while self.mineral_harvester_balance < 0 and 0 < self.gas_harvester_balance:
            harvester = self.request_gas_harvester()
            self.add_mineral_harvester(harvester)

        while 0 < self.mineral_harvester_balance and self.gas_harvester_balance < 0:
            harvester = self.request_mineral_harvester()
            self.add_gas_harvester(harvester)