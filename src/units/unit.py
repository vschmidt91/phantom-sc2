from __future__ import annotations
from typing import TYPE_CHECKING, Optional
import logging
import math
from abc import ABC, abstractmethod, abstractproperty

from sc2.game_data import UnitTypeData
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit, UnitCommand

from ..ai_component import AIComponent
from ..constants import *

if TYPE_CHECKING:
    from ..ai_base import AIBase

class AIUnit(ABC, AIComponent):
    
    def __init__(self, ai: AIBase):
        super().__init__(ai)

    @abstractproperty
    def unit(self) -> Unit:
        raise NotImplementedError()

    @property
    def value(self) -> float:
        health = self.unit.health + self.unit.shield
        dps =  max(self.unit.ground_dps, self.unit.air_dps)
        return math.sqrt(health * dps)

class UnitByTag(AIUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai)
        self.tag = tag

    def __hash__(self) -> int:
        return hash(self.tag)

    @property
    def unit(self) -> Unit:
        return self.ai.unit_manager.unit_by_tag.get(self.tag)

class EnemyUnit(UnitByTag):

    SAMPLE_OFFSETS = {(0, 0), (0, 1), (0, -1), (1, 0), (-1, 0)}

    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.snapshot: Optional[Unit] = None

    @property
    def unit(self) -> Unit:
        unit = super().unit
        if unit and not unit.is_snapshot:
            self.snapshot = unit
        elif (
            self.snapshot
            and all(self.ai.is_visible(self.snapshot.position.offset(o)) for o in self.SAMPLE_OFFSETS)
        ):
            self.snapshot = None

        return self.snapshot

class CommandableUnit(UnitByTag):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        
    def on_step(self) -> None:
        if (
            self.unit
            and (command := self.get_command())
            and not any(self.ai.order_matches_command(o, command) for o in command.unit.orders)
            and not self.ai.do(command, subtract_cost=False, subtract_supply=False)
        ):
            logging.error(f"command failed: {command}")

    @abstractmethod
    def get_command(self) -> Optional[UnitCommand]:
        raise NotImplementedError()

class IdleBehavior(CommandableUnit):

    def __init__(self) -> None:
        super().__init__()

    def get_command(self) -> Optional[UnitCommand]:
        return None