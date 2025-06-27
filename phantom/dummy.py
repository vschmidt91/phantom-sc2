from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import BotAI


class DummyBot(BotAI):
    async def on_start(self):
        await super().on_start()
        bases = sorted(self.expansion_locations_list, key=lambda p: p.distance_to(self.enemy_start_locations[0]))
        await self.client.debug_create_unit(
            [
                [UnitTypeId.RAVAGER, 10, self.game_info.map_center, 1],
                [UnitTypeId.RAVAGER, 10, self.game_info.map_center, 2],
                [UnitTypeId.OVERLORDCOCOON, 1, self.game_info.map_center, 1],
                [UnitTypeId.OVERLORDCOCOON, 1, self.game_info.map_center, 2],
            ]
        )
        for b in bases[1:5]:
            await self.client.debug_create_unit(
                [
                    [UnitTypeId.PROBE, 1, b, 2],
                ]
            )

    async def on_step(self, iteration):
        pass
