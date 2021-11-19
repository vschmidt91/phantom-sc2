
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

class DummyAI(BotAI):

    async def on_start(self):
        await self.client.debug_upgrade()
        bases = sorted(self.expansion_locations_list, key=lambda b:b.distance_to(self.start_location))
        spawns = [
            [UnitTypeId.HATCHERY, 1, b, 2]
            for b in bases[2:-1]
        ]
        await self.client.debug_create_unit(spawns)
    
    async def on_step(self, iteration: int):
        for ling in self.units(UnitTypeId.ZERGLING):
            ling(AbilityId.BURROWDOWN_ZERGLING)
        for ling in self.units(UnitTypeId.ZERGLINGBURROWED):
            ling(AbilityId.BURROWUP_ZERGLING)
        pass 