
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

class DummyAI(BotAI):

    async def on_start(self):
        # self.client.game_step = 1
        # p = self.game_info.map_center
        # d = 8.625
        # await self.client.debug_create_unit([
        #     [UnitTypeId.QUEEN, 1, p, 1],
        #     [UnitTypeId.BANSHEE, 1, p.offset((d, 0)), 1]
        # ])
        pass
    
    async def on_step(self, iteration: int):

        # if not self.units(UnitTypeId.QUEEN):
        #     return

        # queen = self.units(UnitTypeId.QUEEN).first
        # banshee = self.units(UnitTypeId.BANSHEE).first
        # queen.attack(banshee)
        # banshee.move(banshee.position.towards(queen, -10))

        # distance_actual = queen.distance_to(banshee)
        # print('distance_actual =', distance_actual)

        # distance_to_attack = queen.radius + queen.air_range + banshee.radius
        # print('distance_for_attack =', distance_to_attack)

        # attacking_expected = distance_actual <= distance_to_attack
        # print('attacking_expected =', attacking_expected)

        pass

class DummyAI2(BotAI):

    async def on_start(self):
        self.client.game_step = 1
        pass
    
    async def on_step(self, iteration: int):
        pass