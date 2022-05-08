from __future__ import annotations
from typing import Optional, Set, Union, Iterable, Tuple, TYPE_CHECKING
import numpy as np
import random

from s2clientprotocol.common_pb2 import Point
from torch import NoneType
from sc2.constants import SPEED_INCREASE_ON_CREEP_DICT

from sc2.position import Point2
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.data import race_worker
from abc import ABC, abstractmethod

from src.units.unit import CommandableUnit

from ..utils import *
from ..constants import *
from ..behaviors.behavior import Behavior
from ..ai_component import AIComponent
from .module import AIModule
if TYPE_CHECKING:
    from ..ai_base import AIBase

BILE_ABILITY = AbilityId.EFFECT_CORROSIVEBILE

class BileModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.enemy_positions: Dict[int, Point2] = dict()
        self.time: float = 0.0

    async def on_step(self):
        self.enemy_positions = {
            enemy.tag: enemy.unit.position
            for enemy in self.ai.unit_manager.enemies.values()
            if enemy.unit
        }
        self.time = self.ai.time

    def estimate_enemy_velocity(self, unit: Unit) -> Point2:
        previous_position = self.enemy_positions.get(unit.tag) or unit.position
        dt = self.ai.time - self.time
        if 0 < dt:
            dx = unit.position - previous_position
            return dx / dt
        return Point2((0, 0))

class BileBehavior(CommandableUnit):
    
    def __init__(self, ai: AIBase, tag: int):
        super().__init__(ai, tag)
        self.last_used = 0

    def bile_priority(self, target: Unit):
        if not self.ai.is_visible(target.position):
            return 0
        if not self.unit.in_ability_cast_range(BILE_ABILITY, target.position):
            return 0
        if target.is_hallucination:
            return 0
        if target.type_id in CHANGELINGS:
            return 0
        priority = 10 + max(target.ground_dps, target.air_dps)
        priority /= 100 + target.health + target.shield
        priority /= 2 + target.movement_speed
        return priority

    def bile(self) -> Optional[UnitCommand]:

        if self.unit.type_id != UnitTypeId.RAVAGER:
            return None

        if self.ai.state.game_loop < self.last_used + COOLDOWN[AbilityId.EFFECT_CORROSIVEBILE]:
            return None

        targets = (
            target.unit
            for target in self.ai.enumerate_enemies()
            if target.unit
        )
        target: Unit = max(
            targets,
            key = lambda t : self.bile_priority(t),
            default = None
        )
        if not target:
            return None
        if self.bile_priority(target) <= 0:
            return None
        velocity = self.ai.biles.estimate_enemy_velocity(target)
        if 2 < velocity.length:
            velocity = Point2((0, 0))
        predicted_position = target.position + velocity * 50 / 22.4
        self.last_used = self.ai.state.game_loop
        return self.unit(BILE_ABILITY, target=predicted_position)