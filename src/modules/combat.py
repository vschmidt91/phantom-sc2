from __future__ import annotations

from sklearn.cluster import DBSCAN, KMeans
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Iterable, Set, Dict
from sc2_helper.combat_simulator import CombatSimulator
import numpy as np
import math

from scipy.cluster.vq import kmeans

from sc2.unit import UnitCommand, Unit, Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

from ..units.unit import CommandableUnit, EnemyUnit
from .module import AIModule
from ..constants import WORKERS, CIVILIANS, CHANGELINGS

if TYPE_CHECKING:
    from ..ai_base import AIBase


class CombatCluster:

    def __init__(self, center: Point2) -> None:
        self.center: Point2 = center
        self.confidence: float = 1.0
        self.units: List[Unit] = []
        self.enemy_units: List[Unit] = []

class CombatModule(AIModule):

    def __init__(self, ai: AIBase) -> None:
        super().__init__(ai)
        self.threat_level: float = 0.0
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
                and behavior.unit.type_id not in { UnitTypeId.DRONE, UnitTypeId.OVERLORD, UnitTypeId.QUEEN }
            )
        )

    @property
    def enemy_army(self) -> Iterable[EnemyUnit]:
        return (
            behavior
            for behavior in self.ai.unit_manager.enemies.values()
            if behavior.unit
        )

    async def on_step(self):

        army = Units((behavior.unit for behavior in self.army), self.ai)
        enemy_army = Units((enemy.unit for enemy in self.enemy_army), self.ai)
        self.threat_level = 1.0 - self.simulate_fight(army, enemy_army)

        all_units = Units([*army, *enemy_army], self.ai)
        if not any(all_units):
            return

        positions = np.stack([unit.position for unit in all_units])
        num_clusters = 1
        max_clusters = 5
        while num_clusters < max_clusters:
            centroids, distance = kmeans(positions, num_clusters, iter=100)
            if distance < 12.0:
                break
            num_clusters += 1

        clusters = [
            CombatCluster(centroid)
            for centroid in centroids
        ]

        self.cluster_by_tag: Dict[int, CombatCluster] = dict()
        for unit in all_units:
            cluster = min(clusters, key = lambda c : np.linalg.norm(c.center - unit.position))
            if unit.is_mine:
                cluster.units.append(unit)
            else:
                cluster.enemy_units.append(unit)
            self.cluster_by_tag[unit.tag] = cluster
                
        for cluster in clusters:
            cluster.confidence = self.simulate_fight(cluster.units, cluster.enemy_units)
            

class CombatStance(Enum):
    FLEE = 1
    RETREAT = 2
    FIGHT = 3
    ADVANCE = 4


class CombatBehavior(CommandableUnit):

    def __init__(self, ai: AIBase, unit: Unit):
        super().__init__(ai, unit)
        self.fight_enabled: bool = True
        self.fight_stance: CombatStance = CombatStance.FIGHT
        self.fight_target: Optional[EnemyUnit] = None

    def target_priority(self, target: EnemyUnit) -> float:
        if not target.unit:
            return 0.0
        if not self.unit:
            return 0.0
        if not self.ai.can_attack(self.unit, target.unit) and not self.unit.is_detector:
            return 0.0
        if target.unit.is_hallucination:
            return 0.0
        if target.unit.type_id in CHANGELINGS:
            return 0.0
        priority = 1e8

        priority /= 100 + math.sqrt(target.unit.position.distance_to(self.ai.start_location))
        priority /= 3 if target.unit.is_structure else 1
        if target.unit.is_enemy:
            priority /= 100 + target.unit.shield + target.unit.health
        else:
            priority /= 500
        priority *= 3 if target.unit.type_id in WORKERS else 1
        priority /= 10 if target.unit.type_id in CIVILIANS else 1

        priority /= 30.0 + target.unit.position.distance_to(self.unit.position)
        if self.unit.is_detector:
            if target.unit.is_cloaked:
                priority *= 10.0
            if not target.unit.is_revealed:
                priority *= 10.0

        return priority

    def get_stance(self, target: Unit) -> CombatStance:

        cluster = self.ai.combat.cluster_by_tag.get(self.unit.tag)

        if cluster is None:
            return CombatStance.RETREAT

        if self.unit.ground_range < 2:

            if cluster.confidence < 1/2:
                return CombatStance.FLEE
            else:
                return CombatStance.FIGHT
        
        else:

            if cluster.confidence < 1/4:
                return CombatStance.FLEE
            elif cluster.confidence < 2/4:
                return CombatStance.RETREAT
            elif cluster.confidence < 3/4:
                return CombatStance.FIGHT
            else:
                return CombatStance.ADVANCE

    def fight(self) -> Optional[UnitCommand]:

        if not self.fight_enabled:
            return None
        if not self.unit:
            return None

        self.fight_target, _ = max(
            (
                (enemy, priority)
                for enemy in self.ai.unit_manager.enemies.values()
                if 0 < (priority := self.target_priority(enemy))
            ),
            key=lambda p: p[1],
            default=(None, 0)
        )

        target = self.fight_target
        if not target:
            return None
        if not target.unit:
            self.fight_target = None
            return None

        self.fight_stance = self.get_stance(target.unit)

        if self.fight_stance == CombatStance.FLEE:

            retreat_point = self.unit.position.towards(target.unit.position, -12)
            return self.unit.move(retreat_point)

        elif self.fight_stance == CombatStance.RETREAT:

            if (
                    (self.unit.weapon_cooldown or self.unit.is_burrowed)
                    and self.unit.position.distance_to(
                target.unit.position) <= self.unit.radius + self.ai.get_unit_range(
                self.unit) + target.unit.radius + self.unit.distance_to_weapon_ready
            ):
                retreat_point = self.unit.position.towards(target.unit.position, -12)
                return self.unit.move(retreat_point)
            elif self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.unit.radius:
                return self.unit.attack(target.unit.position)
            else:
                return self.unit.attack(target.unit.position)

        elif self.fight_stance == CombatStance.FIGHT:

            if self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.unit.radius:
                return self.unit.attack(target.unit.position)
            else:
                attack_point = target.unit.position
                return self.unit.attack(attack_point)

        elif self.fight_stance == CombatStance.ADVANCE:

            distance = self.unit.position.distance_to(target.unit.position) - self.unit.radius - target.unit.radius
            if self.unit.weapon_cooldown and 1 < distance:
                return self.unit.move(target.unit)
            elif self.unit.position.distance_to(target.unit.position) <= self.unit.radius + self.ai.get_unit_range(
                    self.unit) + target.unit.radius:
                return self.unit.attack(target.unit.position)
            else:
                return self.unit.attack(target.unit.position)

        return None