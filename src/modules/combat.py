from __future__ import annotations

from sklearn.cluster import DBSCAN, KMeans
from enum import Enum
from itertools import chain
from typing import TYPE_CHECKING, List, Optional, Iterable, Set, Dict, Union
from sc2_helper.combat_simulator import CombatSimulator
import numpy as np
import math

from scipy.cluster.vq import kmeans

from ..utils import center

from sc2.unit import UnitCommand, Unit, Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

from ..units.unit import CommandableUnit
from .module import AIModule
from ..constants import WORKERS, CIVILIANS, CHANGELINGS

if TYPE_CHECKING:
    from ..ai_base import AIBase


class CombatStance(Enum):
    FLEE = 1
    RETREAT = 2
    FIGHT = 3
    ADVANCE = 4

class CombatCluster:

    def __init__(self) -> None:
        self.center = Point2((0.0, 0.0))
        self.tags: Set[int] = set()
        self.confidence: float = 1.0
        self.target: Optional[Unit] = None

class CombatModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.confidence: float = 1.0
        self.combat_simulator = CombatSimulator()    
        
    def simulate_fight(self, own_units: Units, enemy_units: Units) -> float:
        """
        rasper: This is a method Paul wrote, it works pretty well most of the time

        Use the combat simulator to predict if our units can beat the enemy units.

        Returns an Enum so that thresholds can be easily adjusted and it may be easier to read the results in other
        code.

        WARNING:
            The combat simulator has some bugs in it that I'm not able to fix since they're in the Rust code. Notable
            bugs include Missile Turrets shooting Hydralisks and 45 SCVs killing a Mutalisk. To get around this, you can
            filter out units that shouldn't be included, such as not including SCVs when seeing if the Mutalisks can win
            a fight (this creates its own problems due to the bounce, but I don't believe the bounce is included in the
            simulation). The simulator isn't perfect, but I think it's still usable. My recommendation is to use it
            cautiously and only when all units involved can attack each other. It definitely doesn't factor good micro
            in, so anything involving spell casters is probably a bad idea.
            - IDPTG/Paul
        """
        
        won_fight, health_remaining = self.combat_simulator.predict_engage(own_units, enemy_units)

        own_health = sum(u.health + u.shield for u in own_units)
        enemy_health = sum(u.health + u.shield for u in enemy_units)
        
        MIN_HEALTH = 1.0
        if won_fight:
            return .5 + .5 * health_remaining / max(MIN_HEALTH, own_health)
        else:
            return .5 - .5 * health_remaining / max(MIN_HEALTH, enemy_health)

    @property
    def army(self) -> Iterable[CombatBehavior]:
        return (
            behavior
            for behavior in self.ai.unit_manager.units.values()
            if (
                isinstance(behavior, CombatBehavior)
                and behavior.fight_enabled
                and behavior.unit
                and behavior.unit.type_id not in CIVILIANS
            )
        )

    async def on_step(self):

        army = Units((behavior.unit for behavior in self.army), self.ai)
        enemy_army = Units((
            unit
            for unit in self.ai.unit_manager.enemies.values()
            if unit.type_id not in CIVILIANS
        ), self.ai)
        self.confidence = self.simulate_fight(army, enemy_army)
            


class CombatBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.fight_enabled: bool = True
        self.stance: CombatStance = CombatStance.FIGHT

        

    def target_priority(self, target: Unit) -> float:
        if not target:
            return 0.0
        if not self.ai.can_attack(self.unit, target) and not self.unit.is_detector:
            return 0.0
        if target.is_hallucination:
            return 0.0
        if target.type_id in CHANGELINGS:
            return 0.0
        priority = 1e8

        priority /= 150 + target.position.distance_to(self.ai.start_location)
        priority /= 3 if target.is_structure else 1
        if target.is_enemy:
            priority /= 100 + target.shield + target.health
        else:
            priority /= 500
        priority *= 3 if target.type_id in WORKERS else 1
        priority /= 10 if target.type_id in CIVILIANS else 1

        priority /= 30.0 + target.position.distance_to(self.unit.position)
        if self.unit.is_detector:
            if target.is_cloaked:
                priority *= 10.0
            if not target.is_revealed:
                priority *= 10.0

        return priority

    def fight(self) -> Optional[UnitCommand]:

        if not self.fight_enabled:
            return None
        if not self.unit:
            return None
            
        confidences = []
        for fight_radius in [20]:
            army_local = Units((
                unit.unit
                for unit in self.ai.combat.army
                if unit.unit.position.distance_to(self.unit.position) < fight_radius
            ), self.ai)
            enemy_army_local = Units((
                unit
                for unit in self.ai.unit_manager.enemies.values()
                if unit.position.distance_to(self.unit.position) < fight_radius
            ), self.ai)
            confidences.append(self.ai.combat.simulate_fight(army_local, enemy_army_local))

        confidence = np.mean(confidences)

        target, _ = max(
            (
                (enemy, priority)
                for enemy in self.ai.unit_manager.enemies.values()
                if 0 < (priority := self.target_priority(enemy))
            ),
            key = lambda p : p[1],
            default = (None, 0)
        )
        if not target:
            return None

        if self.stance == CombatStance.FLEE:
            if 2/3 < confidence:
                self.stance = CombatStance.FIGHT
        elif self.stance == CombatStance.FIGHT:
            if confidence < 1/3:
                self.stance = CombatStance.FLEE

        stance = self.stance

        if stance == CombatStance.FLEE:

            retreat_point = self.unit.position.towards(target.position, -12)
            return self.unit.move(retreat_point)

        elif stance == CombatStance.RETREAT:

            if (
                (self.unit.weapon_cooldown or self.unit.is_burrowed)
                and self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
                self.unit) + target.radius + self.unit.distance_to_weapon_ready
            ):
                retreat_point = self.unit.position.towards(target.position, -12)
                return self.unit.move(retreat_point)
            elif self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.radius:
                return self.unit.attack(target.position)
            else:
                return self.unit.attack(target.position)

        elif stance == CombatStance.FIGHT:

            if self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.radius:
                return self.unit.attack(target.position)
            else:
                attack_point = target.position
                return self.unit.attack(attack_point)

        elif stance == CombatStance.ADVANCE:

            distance = self.unit.position.distance_to(target.position) - self.unit.radius - target.radius
            if self.unit.weapon_cooldown and 1 < distance:
                return self.unit.move(target)
            elif self.unit.position.distance_to(target.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.radius:
                return self.unit.attack(target.position)
            else:
                return self.unit.attack(target.position)

        return None