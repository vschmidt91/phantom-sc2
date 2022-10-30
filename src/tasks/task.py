
from abc import ABC, abstractmethod
from typing import Optional

from sc2.unit import Unit, UnitCommand

from src.units.unit import AIUnit

class Task(ABC):

    def __init__(self) -> None:
        pass

    @abstractmethod
    def get_command(self, unit: AIUnit) -> Optional[UnitCommand]:
        raise NotImplementedError()