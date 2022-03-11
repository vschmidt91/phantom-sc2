
from typing import Union, Iterable, Dict

from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from ..macro_plan import MacroPlan

from .zerg_macro import ZergMacro
from .zerg_strategy import ZergStrategy

class DummyStrategy(ZergStrategy):

    def build_order(self) -> Iterable[Union[UnitTypeId, UpgradeId]]:
        return [
            UnitTypeId.EXTRACTOR,
            UnitTypeId.EXTRACTOR,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
            UnitTypeId.OVERLORD,
        ]


    def update(self, bot):
        bot.scout_manager.scout_enemy_natural = False
        if 6720 <= bot.state.game_loop:
            print(bot.state.score.collected_vespene)
        return super().update(bot)

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