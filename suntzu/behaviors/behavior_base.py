
from typing import Iterable, Optional

from sc2.unit import Unit, UnitCommand
from abc import ABC, abstractmethod

class BehaviorBase(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def execute(self, unit: Unit) -> bool:
        raise NotImplementedError