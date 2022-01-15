import sc2
import random
from sc2.bot_ai import BotAI, Race
from sc2.ids.unit_typeid import UnitTypeId
from typing import Set
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.player import Bot, Computer


class CompetitiveBot(BotAI):
    NAME: str = "Limitless"
    RACE: Race = Race.Terran

    def request_build_order(self):
        self.build_orders = {Race.Protoss: {
            'Widowmine-Drop' : [
                self.build_worker,
                self.build_depot,
                self.build_worker,
                self.build_barracks,
                self.build_worker,
            ]
        }, Race.Terran: {
            'Hellion-Reaper-Opener': [
                self.build_worker,
                self.build_depot,
                self.build_worker,
                self.build_barracks,
                self.build_worker,
            ]
        }, Race.Zerg: {
            'The-Brick' : [
                self.build_worker,
                self.build_depot,
                self.build_worker,
                self.build_barracks,
                self.build_worker,
            ]
        },
            Race.Random: {
                'Fast-Reaper-Expand' : [
                    self.build_worker,
                    self.build_depot,
                    self.build_worker,
                    self.build_barracks,
                    self.build_worker,
                ]
            }}
        return random.choice(list(self.build_orders[self.enemy_race].values()))

    async def build_depot(self):
        CommandCenter = self.townhalls.ready.random
        Position = CommandCenter.position.towards(self.enemy_start_locations[0], 8)
        if (
            self.can_afford(UnitTypeId.SUPPLYDEPOT) and
            self.supply_left <= 3 and
            self.already_pending(UnitTypeId.SUPPLYDEPOT) == 0
        ):
            await self.build(UnitTypeId.SUPPLYDEPOT, near = Position)
            return True
        return False

    async def build_worker(self):
        CommandCenter = self.townhalls.ready.random
        if (
                self.can_afford(UnitTypeId.SCV) and
                CommandCenter.is_idle and
                self.supply_left >= 3
        ):
            CommandCenter.train(UnitTypeId.SCV)
            return True
        return False

    async def build_barracks(self):
        Position = self.start_location.towards(self.game_info.map_center, 8)
        if (
                self.can_afford(UnitTypeId.BARRACKS) and
                self.already_pending(UnitTypeId.BARRACKS) == 0 and
                self.structures(UnitTypeId.BARRACKS).amount < 12
        ):
            await self.build(UnitTypeId.BARRACKS, near = Position)
            return True
        return False

    async def on_start(self):
        print("Started")
        await self.chat_send('GL HF! Become Limitless.')
        self.current_action_index = 0
        self.actions_complete = False
        self.action_list = self.request_build_order()
        print("ended")

    def has_more_actions(self) :
        return self.current_action_index < len(self.action_list) - 1

    async def on_step(self, iteration):
        if not self.actions_complete:
            print("hi")
            action_was_successful = await self.action_list[self.current_action_index]()
            print("ya")
            if action_was_successful:
                print("ok")
                self.current_action_index += 1  # ...then progress to the next action

                # Once we've run out of actions, we're done!
                if not self.has_more_actions():
                    self.actions_complete = True
        pass

    def on_end(self, result):
        pass