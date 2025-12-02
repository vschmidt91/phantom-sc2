from collections import Counter
from random import random, choice, shuffle

from ares import AresBot
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import BotAI
from sc2.position import Point2


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


class BaseBlock(AresBot):
    async def on_start(self) -> None:
        await super().on_start()
        await self.client.debug_create_unit(
            [
                [UnitTypeId.ZERGLINGBURROWED, 1, self.mediator.get_enemy_nat, 2],
                [UnitTypeId.ZERGLINGBURROWED, 1, self.mediator.get_enemy_third, 2],
                [UnitTypeId.ZERGLINGBURROWED, 1, self.mediator.get_enemy_fourth, 2],
            ]
        )

    async def on_step(self, iteration):
        pass


class CannonRush(AresBot):
    async def on_start(self) -> None:
        await super().on_start()
        await self.client.debug_create_unit(
            [
                [UnitTypeId.PYLON, 1, self.mediator.get_enemy_nat, 2],
                [UnitTypeId.PHOTONCANNON, 1, self.mediator.get_enemy_nat + Point2((0, -2)), 2],
                [UnitTypeId.PHOTONCANNON, 1, self.mediator.get_enemy_nat + Point2((0, +2)), 2],
                [UnitTypeId.PHOTONCANNON, 1, self.mediator.get_enemy_nat + Point2((-2, 0)), 2],
                [UnitTypeId.PHOTONCANNON, 1, self.mediator.get_enemy_nat + Point2((+2, 0)), 2],
            ]
        )

    async def on_step(self, iteration):
        pass


class BunkerTestBot(AresBot):
    async def on_start(self):
        await super().on_start()
        await self.client.debug_create_unit(
            [
                [UnitTypeId.BUNKER, 1, self.mediator.get_enemy_nat, 2],
                [UnitTypeId.MARINE, 4, self.mediator.get_enemy_nat, 2],
                [UnitTypeId.MARAUDER, 2, self.mediator.get_enemy_nat, 2],
                [UnitTypeId.REAPER, 4, self.mediator.get_enemy_nat, 2],
                [UnitTypeId.GHOST, 2, self.mediator.get_enemy_nat, 2],
            ]
        )
        self.passenger_types_to_buffs = dict[frozenset, frozenset]()

    async def on_step(self, iteration):
        await super().on_step(iteration)
        bunkers = self.structures(UnitTypeId.BUNKER)
        if not bunkers:
            return
        bunker: Unit = bunkers[0]
        passenger_types = frozenset(Counter(p.type_id for p in bunker.passengers).items())
        buffs = frozenset(bunker._proto.buff_ids)

        # check consistency
        if previous_buffs := self.passenger_types_to_buffs.get(passenger_types):
            if buffs != previous_buffs:
                raise Exception("inconsistent buffs detected")
        else:
            self.passenger_types_to_buffs[passenger_types] = buffs

        if bunker.passengers:
            bunker(AbilityId.UNLOADALL_BUNKER)
        else:
            # some deterministic tests first
            if iteration == 2:
                passengers = self.units(UnitTypeId.MARINE)
            elif iteration == 4:
                passengers = self.units(UnitTypeId.REAPER)
            else:
                # load random subset
                passenger_count = choice([1, 2, 3, 4])
                passengers = list(self.units({UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.REAPER, UnitTypeId.GHOST}))
                shuffle(passengers)
                passengers = passengers[:passenger_count]
            for passenger in passengers:
                passenger.smart(bunker)

        if len(self.passenger_types_to_buffs) == 30:
            print("All combinations tested.")
            for key, buffs in self.passenger_types_to_buffs.items():
                key_pretty = ", ".join([f"{count} {type_id.name}" for type_id, count in key])
                print(key_pretty, " => ", set(buffs))
            await self.client.leave()
