
from __future__ import annotations
import math
from typing import Union, Iterable, Dict, TYPE_CHECKING
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.data import Race
from src.unit_counters import UNIT_COUNTER_DICT
from ..constants import BUILD_ORDER_PRIORITY, ZERG_ARMOR_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES
from ..cost import Cost
from ..macro_plan import MacroPlan
from ..utils import unitValue

from .zerg_strategy import ZergStrategy

from ..ai_base import AIBase

class ZergMacro(ZergStrategy):

    def __init__(self, ai: AIBase):
        super().__init__(ai)
        self.tech_up: bool = False
        self.straight_hydra: bool = False

    def composition(self) -> Dict[UnitTypeId, int]:

        worker_limit = 80
        enemy_max_workers = 22 * self.ai.block_manager.enemy_base_count
        worker_target = min(
            worker_limit,
            self.ai.get_max_harvester(),
            # enemy_max_workers + 11,
        )
        worker_target = max(worker_target, 1)
        worker_count = self.ai.count(UnitTypeId.DRONE, include_planned=False)
        ratio = max(
            self.ai.threat_level,
            worker_count / worker_target,
            # -3 + 4 * (worker_count / worker_target),
        )
        ratio = max(0, min(1, ratio))

        enemy_value = {
            tag: self.ai.get_unit_value(enemy)
            for tag, enemy in self.ai.enemies.items()
        }
        enemy_flyer_value = sum(enemy_value[e.tag] for e in self.ai.enemies.values() if e.is_flying)
        enemy_ground_value = sum(enemy_value[e.tag] for e in self.ai.enemies.values() if not e.is_flying)
        enemy_flyer_ratio = enemy_flyer_value / max(1, enemy_flyer_value + enemy_ground_value)

        queen_target = min(5, 1 + self.ai.townhalls.amount)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: queen_target,
        }

        if UpgradeId.ZERGLINGMOVEMENTSPEED in self.ai.state.upgrades:
            composition[UnitTypeId.ROACHWARREN] = 1
            composition[UnitTypeId.OVERSEER] = 1

        if self.ai.count(UnitTypeId.LAIR, include_pending=False, include_planned=False) + self.ai.count(UnitTypeId.HIVE, include_pending=False, include_planned=False):
            composition[UnitTypeId.HYDRALISKDEN] = 1
            composition[UnitTypeId.OVERSEER] = 2

        if self.ai.count(UnitTypeId.HIVE, include_pending=False, include_planned=False):
            composition[UnitTypeId.CORRUPTOR] = 0
            composition[UnitTypeId.BROODLORD] = 0
            composition[UnitTypeId.OVERSEER] = 3

        army_composition = {
            UnitTypeId.ZERGLING: 1.0,
            UnitTypeId.ROACH: 0.0,
            UnitTypeId.HYDRALISK: 0.0,
            UnitTypeId.BROODLORD: 0.0,
            UnitTypeId.CORRUPTOR: 0.0,
        }

        can_build = {
            t: not any(self.ai.get_missing_requirements(t, include_pending=False, include_planned=False))
            for t in army_composition
        }

        for enemy in self.ai.enumerate_enemies():
            if counters := UNIT_COUNTER_DICT.get(enemy.type_id):
                for t in counters:
                    if can_build[t]:
                        count = self.ai.get_unit_cost(enemy.type_id) / self.ai.get_unit_cost(t)
                        army_composition[t] += 2 * ratio * count
                        break

        composition.update({ k: int(v) for k, v in army_composition.items() if 0 < v })

        # if self.ai.count(UnitTypeId.HIVE, include_planned=False):
        #     if self.ai.count(UnitTypeId.SPIRE) + self.ai.count(UnitTypeId.GREATERSPIRE) == 0:
        #         composition[UnitTypeId.SPIRE] = 1
        #     composition[UnitTypeId.CORRUPTOR] = max(3, int(ratio * 20 * enemy_flyer_ratio))
        #     composition[UnitTypeId.BROODLORD] = int(ratio * 12 * (1 - enemy_flyer_ratio))

        return composition

    def destroy_destructables(self) -> bool:
        return 5 * 60 < self.ai.time

    def filter_upgrade(self, upgrade) -> bool:
        if upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL1:
            return UpgradeId.ZERGMISSILEWEAPONSLEVEL2 in self.ai.state.upgrades
        elif upgrade == UpgradeId.ZERGGROUNDARMORSLEVEL2:
            return UpgradeId.ZERGMISSILEWEAPONSLEVEL3 in self.ai.state.upgrades
        return super().filter_upgrade(upgrade)

    def steps(self):

        steps = {
            self.ai.update_tables: 1,
            self.ai.handle_errors: 1,
            self.ai.handle_actions: 1,
            self.ai.update_maps: 1,
            self.ai.handle_delayed_effects: 1,
            self.ai.update_bases: 1,
            self.ai.update_composition: 1,
            self.ai.update_gas: 1,
            self.ai.morph_overlords: 1,
            self.ai.make_composition: 1,
            self.ai.make_tech: 1,
            self.ai.expand: 1,
            self.ai.assess_threat_level: 1,
            self.ai.update_strategy: 1,
            self.ai.macro: 1,
            self.ai.micro: 1,
            self.ai.save_enemy_positions: 1,
            self.ai.make_defenses: 1,
            self.ai.draw_debug: 1,
        }

        return steps