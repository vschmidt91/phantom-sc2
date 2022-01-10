
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

class DummyAI(BotAI):

    async def on_start(self):
        # await self.client.debug_create_unit([
        #     [UnitTypeId.ZERGLING, 1, b, 2]
        #     for b in self.expansion_locations_list
        # ])
        await self.client.debug_create_unit([
            [UnitTypeId.RAVAGER, 5, self.game_info.map_center, 1],
            [UnitTypeId.RAVAGER, 5, self.game_info.map_center, 2]
        ])
        pass
    
    async def on_step(self, iteration: int):
        pass 