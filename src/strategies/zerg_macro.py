
import math
from typing import Union, Iterable, Dict
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.data import Race
from ..constants import BUILD_ORDER_PRIORITY, ZERG_ARMOR_UPGRADES, ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_MELEE_UPGRADES, ZERG_RANGED_UPGRADES
from ..cost import Cost
from ..macro_plan import MacroPlan
from ..utils import unitValue

from .zerg_strategy import ZergStrategy

class ZergMacro(ZergStrategy):

    def __init__(self):
        self.tech_up: bool = False
        self.straight_hydra: bool = False

    def composition(self, bot) -> Dict[UnitTypeId, int]:

        worker_limit = 100
        enemy_max_workers = 22 * bot.block_manager.enemy_base_count
        worker_target = min(
            worker_limit,
            bot.get_max_harvester(),
            # enemy_max_workers + 11,
        )
        worker_target = max(worker_target, 1)
        worker_count = bot.count(UnitTypeId.DRONE, include_planned=False)
        ratio = max(
            bot.threat_level,
            pow(worker_count / worker_target, 2),
        )
        ratio = min(1, ratio)
        # ratio = pow(ratio, 8)
        # ratio = 1 if 0.5 < ratio else 0

        enemy_value = {
            tag: bot.get_unit_value(enemy.type_id)
            for tag, enemy in bot.enemies.items()
        }
        enemy_flyer_value = sum(enemy_value[e.tag] for e in bot.enemies.values() if e.is_flying)
        enemy_ground_value = sum(enemy_value[e.tag] for e in bot.enemies.values() if not e.is_flying)
        enemy_flyer_ratio = enemy_flyer_value / max(1, enemy_flyer_value + enemy_ground_value)

        queen_target = min(5, 1 + bot.townhalls.amount)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: queen_target,
        }

        tech_up = 40 <= worker_count and 3 <= bot.townhalls.amount

        # composition[UnitTypeId.ZERGLING] = 0
        # if 2.5 * 60 <= bot.time:
        #     composition[UnitTypeId.ROACH] = 0

        # tech_up = True

        if tech_up:
            composition[UnitTypeId.ROACH] = 0
            composition[UnitTypeId.HYDRALISK] = 0
            # composition[UnitTypeId.EVOLUTIONCHAMBER] = 2
            if bot.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL1, include_planned=False, include_pending=False):
                composition[UnitTypeId.EVOLUTIONCHAMBER] = 2
                # composition[UnitTypeId.HYDRALISK] = 0
            
        if 1 <= bot.count(UnitTypeId.LAIR, include_pending=False, include_planned=False) + bot.count(UnitTypeId.HIVE, include_pending=False, include_planned=False):
            composition[UnitTypeId.OVERSEER] = 2

        if bot.count(UnitTypeId.ROACHWARREN, include_planned=False):
        # if tech_up:
            if bot.count(UnitTypeId.HYDRALISKDEN, include_pending=False, include_planned=False):
                hydra_ratio = enemy_flyer_ratio
                composition[UnitTypeId.ROACH] = int(ratio * worker_target * (1 - hydra_ratio))
                composition[UnitTypeId.HYDRALISK] = int(ratio * worker_target * hydra_ratio)
            else:
                composition[UnitTypeId.ROACH] = int(ratio * worker_target)
                composition[UnitTypeId.RAVAGER] = int(1/5 * ratio * worker_target)
                # composition[UnitTypeId.ZERGLING] = int(ratio * enemy_ground_value / 50)
        else:
            composition[UnitTypeId.ZERGLING] = max(1, int(ratio * enemy_ground_value / 12.5))

        if bot.count(UnitTypeId.HIVE, include_planned=False):
            if bot.count(UnitTypeId.SPIRE) + bot.count(UnitTypeId.GREATERSPIRE) == 0:
                composition[UnitTypeId.SPIRE] = 1
            composition[UnitTypeId.CORRUPTOR] = max(3, int(ratio * 20 * enemy_flyer_ratio))
            composition[UnitTypeId.BROODLORD] = int(ratio * 12 * (1 - enemy_flyer_ratio))

        return composition

    def destroy_destructables(self, bot) -> bool:
        return 5 * 60 < bot.time

    def filter_upgrade(self, bot, upgrade) -> bool:
        # if upgrade in ZERG_FLYER_UPGRADES:
        #     return False
        # elif upgrade in ZERG_FLYER_ARMOR_UPGRADES:
        #     return False
        # elif upgrade in ZERG_MELEE_UPGRADES:
        #     return False
        # elif upgrade in ZERG_ARMOR_UPGRADES:
        #     return self.tech_up
        # elif upgrade in ZERG_RANGED_UPGRADES:
        #     return self.tech_up
        # elif upgrade == UpgradeId.GLIALRECONSTITUTION:
        #     return self.tech_up
        # elif upgrade == UpgradeId.ZERGLINGMOVEMENTSPEED:
        #     return False
        return True

    def steps(self, bot):

        steps = {
            bot.update_tables: 1,
            bot.handle_errors: 1,
            bot.handle_actions: 1,
            bot.update_maps: 1,
            bot.handle_delayed_effects: 1,
            bot.update_bases: 1,
            bot.update_composition: 1,
            bot.update_gas: 1,
            bot.morph_overlords: 1,
            bot.make_composition: 1,
            bot.make_tech: 1,
            bot.expand: 1,
            bot.assess_threat_level: 1,
            bot.update_strategy: 1,
            bot.macro: 1,
            bot.micro: 1,
            bot.save_enemy_positions: 1,
            bot.make_defenses: 1,
            bot.draw_debug: 1,
        }

        return steps