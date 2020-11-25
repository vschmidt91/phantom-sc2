
from sc2 import BotAI
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units

class BotStrategy(object):

    def __init__(self):
        self.harvestGas = True
        self.destroyRocks = True

    def getChain(self, bot: BotAI):
        return [bot.macro]

    async def getTargets(self, bot: BotAI):
        return []

    async def on_before_start(self, bot: BotAI):
        pass

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