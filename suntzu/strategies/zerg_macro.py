
import math
from typing import Union, Iterable, Dict
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.data import Race
from suntzu.constants import BUILD_ORDER_PRIORITY, ZERG_FLYER_ARMOR_UPGRADES, ZERG_FLYER_UPGRADES, ZERG_MELEE_UPGRADES
from suntzu.cost import Cost
from suntzu.macro_plan import MacroPlan
from suntzu.utils import unitValue

from .zerg_strategy import ZergStrategy

class ZergMacro(ZergStrategy):

    def __init__(self):
        self.enable_expansion = False

    def composition(self, bot) -> Dict[UnitTypeId, int]:

        worker_limit = 88
        worker_target = min(worker_limit, bot.get_max_harvester())
        worker_count = bot.count(UnitTypeId.DRONE, include_planned=False)
        ratio = min(1, max(bot.threat_level, worker_count / worker_limit))
        # ratio = pow(ratio, 8)
        # ratio = 1 if 0.5 < ratio else 0

        enemy_value = {
            tag: unitValue(enemy)
            for tag, enemy in bot.enemies.items()
        }
        enemy_flyer_value = sum(enemy_value[e.tag] for e in bot.enemies.values() if e.is_flying)
        enemy_ground_value = sum(enemy_value[e.tag] for e in bot.enemies.values() if not e.is_flying)
        enemy_flyer_ratio = enemy_flyer_value / max(1, enemy_flyer_value + enemy_ground_value)

        queen_target = 2 * bot.townhalls.amount
        # if not self.enable_expansion:
        #     queen_target = 8
        queen_target = min(8, queen_target)

        composition = {
            UnitTypeId.DRONE: worker_target,
            UnitTypeId.QUEEN: queen_target,
        }

        if (
            bot.count(UpgradeId.ZERGLINGMOVEMENTSPEED, include_pending=False, include_planned=False)
            and 38 <= bot.bases.harvester_count
            and 3 <= bot.townhalls.amount
        ):
            composition[UnitTypeId.ROACH] = 0
        # else:
        #     composition[UnitTypeId.BANELINGNEST] = 1
        
        if not bot.count(UnitTypeId.ROACHWARREN, include_pending=False, include_planned=False):
            composition[UnitTypeId.ZERGLING] = 2 + int(ratio * enemy_ground_value / 350)
        else:
            composition[UnitTypeId.OVERSEER] = 2
            # composition[UnitTypeId.EVOLUTIONCHAMBER] = 2
            if 0.2 < enemy_flyer_ratio or bot.count(UnitTypeId.HIVE, include_planned=False):
                composition[UnitTypeId.ROACH] = int(ratio * (1 - enemy_flyer_ratio) * 40)
                composition[UnitTypeId.HYDRALISK] = int(ratio * enemy_flyer_ratio * 40)
            else:
                composition[UnitTypeId.ROACH] = int(ratio * 50)
                composition[UnitTypeId.RAVAGER] = int(ratio * 10)

        if bot.count(UnitTypeId.HIVE, include_planned=False):
            if 0.2 < enemy_flyer_ratio:
                composition[UnitTypeId.CORRUPTOR] = 10
            else:
                composition[UnitTypeId.CORRUPTOR] = 3
                composition[UnitTypeId.BROODLORD] = 10

        return composition

    def destroy_destructables(self, bot) -> bool:
        return 4 * 60 < bot.time

    def filter_upgrade(self, bot, upgrade) -> bool:
        if upgrade in ZERG_FLYER_UPGRADES:
            return False
        if upgrade in ZERG_FLYER_ARMOR_UPGRADES:
            return False
        if upgrade in ZERG_MELEE_UPGRADES:
            return False
        return True

    def update(self, bot):

        # if bot.actual_by_type[UnitTypeId.SPAWNINGPOOL]:
        #     if bot.planned_by_type[UnitTypeId.NOTAUNIT]:
        #         for plan in list(bot.planned_by_type[UnitTypeId.NOTAUNIT]):
        #             bot.remove_macro_plan(plan) 
        # else:
        #     if not bot.planned_by_type[UnitTypeId.NOTAUNIT]:
        #         plan = MacroPlan(UnitTypeId.NOTAUNIT)
        #         plan.cost = Cost(1000, 0, 200)
        #         plan.priority = BUILD_ORDER_PRIORITY
        #         bot.add_macro_plan(plan)

        if 2 <= bot.enemy_base_count:
            self.enable_expansion = True
        elif 32 <= bot.bases.harvester_count:
            self.enable_expansion = True

        return super().update(bot)

    def steps(self, bot):

        steps = {
            # bot.kill_random_unit: 100,
            bot.update_tables: 1,
            bot.handle_errors: 1,
            bot.handle_actions: 1,
            bot.update_maps: 1,
            bot.handle_delayed_effects: 1,
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
            bot.draft_civilians: 1,
            # bot.expand: 1,
            bot.micro: 1,
            bot.assess_threat_level: 1,
            bot.macro: 1,
            bot.update_strategy: 1,
            bot.save_enemy_positions: 1,
            bot.reset_blocked_bases: 1,
            bot.assign_idle_workers: 1,
            bot.reset_blocked_bases: 1,
            bot.greet_opponent: 1,
            bot.make_defenses: 1,
            bot.draw_debug: 1,
        }

        if self.enable_expansion:
            steps[bot.expand] = 1

        return steps