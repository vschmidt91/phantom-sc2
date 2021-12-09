
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

class DummyAI(BotAI):

    async def on_start(self):
        pass
    
    async def on_step(self, iteration: int):
        await self.client.debug_leave()
        pass 