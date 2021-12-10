
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

class DummyAI(BotAI):

    async def on_start(self):
        bases = sorted(self.expansion_locations, key = lambda b : b.distance_to(self.start_location))
        await self.client.debug_create_unit([
            [UnitTypeId.ZERGLINGBURROWED, 1, b, 2]
            for b in bases[3:-3]
        ])
        pass
    
    async def on_step(self, iteration: int):
        # await self.client.debug_leave()
        pass 