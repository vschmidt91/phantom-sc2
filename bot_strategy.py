
from sc2 import BotAI, Race
from sc2.data import Result, race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units

STATIC_DEFENSE = {
    Race.Protoss: { UnitTypeId.PHOTONCANNON },
    Race.Terran: { UnitTypeId.MISSILETURRET },
    Race.Zerg: { UnitTypeId.SPINECRAWLER, UnitTypeId.SPORECRAWLER },
}

class BotStrategy(object):

    def __init__(self):
        self.harvestGas = True
        self.destroyRocks = True

    def getChain(self, bot: BotAI):
        return [bot.macro]

    async def getTargetPosition(self, bot: BotAI, target: UnitTypeId, trainer: UnitTypeId):
        if target in STATIC_DEFENSE[bot.race]:
            defenses = bot.structures(STATIC_DEFENSE[bot.race])
            undefendedTownhalls = bot.townhalls.filter(lambda t : not defenses.closer_than(8, t).exists)
            if undefendedTownhalls.exists:
                townhall = undefendedTownhalls.closest_to(trainer)
                if townhall.position in bot.expansion_locations_list:
                    return bot.expansion_locations_dict[townhall.position].center
                else:
                    return townhall.position.towards(bot.game_info.map_center, -2)
        elif bot.isStructure(target):
            if target in race_townhalls[bot.race]:
                return await bot.get_next_expansion()
                # if bot.enemy_structures.exists:
                #     awayFrom = bot.enemy_structures
                # else:
                #     awayFrom = bot.enemy_start_locations
                # expansions = (b for b in bot.expansion_locations_list if b not in bot.owned_expansions)
                # expansions = sorted(expansions, key=lambda b : max((b.distance_to(t) for t in bot.owned_expansions.keys())) - min((b.distance_to(e) for e in awayFrom)))
                # return expansions[0]
            else:
                position = bot.townhalls.random.position
                return position.towards(bot.game_info.map_center, 3)
        else:
            return trainer.position
        return None

    async def getTargets(self, bot: BotAI):
        return []

    async def on_building_construction_complete(self, bot: BotAI, unit: UnitTypeId):
        pass

    async def on_building_construction_started(self, bot: BotAI, unit: Unit):
        pass

    async def on_end(self, bot: BotAI, game_result: Result):
        pass

    async def on_enemy_unit_entered_vision(self, bot: BotAI, unit: Unit):
        pass

    async def on_enemy_unit_left_vision(self, bot: BotAI, unit_tag: int):
        pass

    async def on_start(self, bot: BotAI):
        pass

    async def on_step(self, bot: BotAI, iteration: int):
        pass

    async def on_unit_created(self, bot: BotAI, unit: Unit):
        pass

    async def on_unit_destroyed(self, bot: BotAI, unit_tag: int):
        pass

    async def on_unit_took_damage(self, bot: BotAI, unit: Unit, amount_damage_taken: float):
        pass

    async def on_unit_type_changed(self, bot: BotAI, unit: Unit, previous_type: UnitTypeId):
        pass

    async def on_upgrade_complete(self, bot: BotAI, upgrade: UpgradeId):
        pass