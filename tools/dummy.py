from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit


class DummyAI(BotAI):

    async def on_start(self):
        self.client.game_step = 1
        # p = self.game_info.map_center
        # d = 8.625
        pass

    async def on_step(self, iteration: int):

        if iteration == 0:
            await self.client.debug_create_unit([
                [UnitTypeId.NYDUSCANAL, 1, self.start_location.towards(self.game_info.map_center, 8), 1],
                [UnitTypeId.ZERGLING, 10, self.start_location, 1],
            ])
            await self.client.debug_tech_tree()
            await self.client.debug_free()
            await self.client.debug_fast_build()
            
        if not self.structures(UnitTypeId.NYDUSCANAL):
            return

        nydus = self.structures(UnitTypeId.NYDUSCANAL).first
        if iteration == 10:
            for ling in self.units(UnitTypeId.ZERGLING):
                ling(AbilityId.SMART, nydus)
            nydus(AbilityId.RALLY_BUILDING, self.game_info.map_center)
        elif iteration == 100:
            nydus(AbilityId.UNLOADALL)
        elif iteration == 104:
            nydus(AbilityId.STOP)

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


class DummyAI2(BotAI):

    async def on_start(self):
        self.client.game_step = 1
        pass

    async def on_step(self, iteration: int):
        pass
