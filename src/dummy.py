from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit


class DummyAI(BotAI):

    async def on_start(self):
        # self.client.game_step = 1
        # p = self.game_info.map_center
        # d = 8.625
        pass

    async def on_building_construction_started(self, unit: Unit):
        print(f'building_construction_started: {unit}')

    async def on_building_construction_complete(self, unit: Unit):
        print(f'building_construction_complete: {unit}')

    async def on_unit_destroyed(self, unit_tag: int):
        print(f'unit_destroyed: {unit_tag}')

    async def on_unit_created(self, unit: Unit):
        print(f'unit_created: {unit}')

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        print(f'unit_type_changed: {previous_type} -> {unit}')

    async def on_step(self, iteration: int):
        await self.expand_now()

        # if iteration == 0:
        #     await self.client.debug_create_unit([
        #         [UnitTypeId.OVERLORD, 5, self.start_location, 1],
        #         [UnitTypeId.LARVA, 50, self.start_location, 1],
        #         [UnitTypeId.HYDRALISK, 1, self.start_location, 1],
        #         [UnitTypeId.ROACH, 1, self.start_location, 1],
        #         [UnitTypeId.ZERGLING, 1, self.start_location, 1],
        #         [UnitTypeId.CORRUPTOR, 1, self.start_location, 1],
        #     ])
        #     await self.client.debug_tech_tree()
        #     await self.client.debug_free()
        #     await self.client.debug_fast_build()

        # elif iteration == 10:
        #     self.units(UnitTypeId.ZERGLING).first(AbilityId.MORPHZERGLINGTOBANELING_BANELING)
        # elif iteration == 20:
        #     self.units(UnitTypeId.ROACH).first(AbilityId.MORPHTORAVAGER_RAVAGER)
        # elif iteration == 30:
        #     self.units(UnitTypeId.HYDRALISK).first(AbilityId.MORPH_LURKER)
        # elif iteration == 40:
        #     self.units(UnitTypeId.OVERLORD).first(AbilityId.MORPH_OVERSEER)
        # elif iteration == 50:
        #     self.units(UnitTypeId.OVERLORD).first(AbilityId.MORPH_OVERLORDTRANSPORT)
        # elif iteration == 60:
        #     self.units(UnitTypeId.CORRUPTOR).first(AbilityId.MORPHTOBROODLORD_BROODLORD)

        # elif iteration == 70:
        #     self.larva.first.train(UnitTypeId.DRONE)
        # elif iteration == 80:
        #     self.larva.first.train(UnitTypeId.ZERGLING)
        # elif iteration == 90:
        #     self.larva.first.train(UnitTypeId.ROACH)
        # elif iteration == 100:
        #     self.larva.first.train(UnitTypeId.HYDRALISK)
        # elif iteration == 110:
        #     self.larva.first.train(UnitTypeId.INFESTOR)
        # elif iteration == 120:
        #     self.larva.first.train(UnitTypeId.SWARMHOSTMP)
        # elif iteration == 130:
        #     self.larva.first.train(UnitTypeId.ULTRALISK)
        # elif iteration == 140:
        #     self.larva.first.train(UnitTypeId.MUTALISK)
        # elif iteration == 150:
        #     self.larva.first.train(UnitTypeId.CORRUPTOR)


class DummyAI2(BotAI):

    async def on_start(self):
        self.client.game_step = 1
        pass

    async def on_step(self, iteration: int):
        pass
