
import math
from typing import Union, Iterable, Dict
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.data import Race
from suntzu.constants import ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_MELEE_UPGRADES
from suntzu.utils import unitValue

from .zerg_strategy import ZergStrategy

class ZergMacro(ZergStrategy):

    def composition(self, bot) -> Dict[UnitTypeId, int]:

        worker_limit = 88
        worker_target = min(worker_limit, bot.get_max_harvester())
        worker_count = bot.count(UnitTypeId.DRONE, include_planned=False)

        ratio = max(bot.threat_level, pow(worker_count / worker_limit, 2))
        # ratio = bot.threat_level

        enemy_value = {
            tag: unitValue(enemy)
            for tag, enemy in bot.enemies.items()
        }
        enemy_flyer_value = sum(enemy_value[e.tag] for e in bot.enemies.values() if e.is_flying)
        enemy_ground_value = sum(enemy_value[e.tag] for e in bot.enemies.values() if not e.is_flying)
        enemy_flyer_ratio = enemy_flyer_value / max(1, enemy_flyer_value + enemy_ground_value)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: min(8, 2 * bot.townhalls.amount),
        }
        if 4 <= bot.townhalls.amount:
            composition[UnitTypeId.QUEEN] += 1

        if 3 <= bot.townhalls.amount:
            composition[UnitTypeId.ROACH] = 0
    
        if not bot.count(UnitTypeId.ROACHWARREN, include_planned=False, include_pending=False):
            composition[UnitTypeId.ZERGLING] = 2 + int(ratio * worker_count)

        elif not bot.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL2, include_planned=False):
            composition[UnitTypeId.OVERSEER] = 1
            composition[UnitTypeId.ROACH] = int(ratio * 50)
            composition[UnitTypeId.RAVAGER] = int(ratio * 10)
        elif not bot.count(UpgradeId.ZERGMISSILEWEAPONSLEVEL3, include_planned=False):
            composition[UnitTypeId.OVERSEER] = 2
            composition[UnitTypeId.ROACH] = int((1 - enemy_flyer_ratio) * 80)
            composition[UnitTypeId.HYDRALISK] = int(enemy_flyer_ratio * 80)
        else:
            composition[UnitTypeId.OVERSEER] = 3
            composition[UnitTypeId.ROACH] = int((1 - enemy_flyer_ratio) * 80)
            composition[UnitTypeId.HYDRALISK] = int(enemy_flyer_ratio * 80)
            composition[UnitTypeId.CORRUPTOR] = 3 + int(enemy_flyer_ratio * 10)
            composition[UnitTypeId.BROODLORD] = 3 + int((1 - enemy_flyer_ratio) * 10)

        # else:
        #     composition[UnitTypeId.LAIR] = 1
        #     composition[UnitTypeId.OVERSEER] = 3
        #     composition.update({
        #         u: int(ratio * v)
        #         for u, v in bot.counter_composition(bot.enemies.values()).items()
        #     })

        # for morph_to in [UnitTypeId.BANELING, UnitTypeId.RAVAGER, UnitTypeId.LURKERMP, UnitTypeId.BROODLORD]:
        #     morph_from = UNIT_TRAINED_FROM[morph_to]
        #     if morph_to in composition:
        #         for morph_from in UNIT_TRAINED_FROM[morph_to]:
        #             composition[morph_from] = math.ceil(composition[morph_to] / 5)

        return composition

    def destroy_destructables(self, bot) -> bool:
        return self.tech_time < bot.time

    def filter_upgrade(self, bot, upgrade) -> bool:
        if upgrade in ZERG_FLYER_UPGRADES:
            return False
        if upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return False
        if upgrade in ZERG_MELEE_UPGRADES:
            return False
        return True

    def steps(self, bot):

        steps = {
            # self.kill_random_unit: 100,
            bot.draw_debug: 1,
            bot.assess_threat_level: 1,
            bot.update_tables: 1,
            bot.handle_errors: 1,
            bot.handle_actions: 1,
            bot.handle_corrosive_biles: 1,
            bot.update_bases: 1,
            bot.update_composition: 1,
            bot.update_gas: 1,
            bot.manage_queens: 1,
            bot.spread_creep: 1,
            bot.scout: 1,
            bot.extractor_trick: 1,
            bot.morph_overlords: 1,
            bot.make_composition: 1,
            bot.make_tech: 1,
            bot.pull_workers: 1,
            bot.expand: 1,
            bot.micro: 1,
            bot.macro: 1,
            bot.transfuse: 1,
            bot.corrosive_bile: 1,
            bot.update_strategy: 1,
            bot.save_enemy_positions: 1,
            bot.reset_blocked_bases: 1,
            bot.assign_idle_workers: 1,
            bot.reset_blocked_bases: 1,
            bot.greet_opponent: 1,
            bot.make_defenses: 1,
        }

        # if UpgradeId.ZERGLINGMOVEMENTSPEED in bot.state.upgrades:
        #     steps[bot.expand] = 1

        return steps